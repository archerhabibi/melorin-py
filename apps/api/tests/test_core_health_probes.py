"""Phase 3.17: readiness probes extracted from app.ready keep their exact semantics."""

import time

import pytest

from melorin.core import health
from melorin.core.health import DatabaseProbe, WorkerProbe, build_checks


class _Redis:
    def __init__(self, tick=None, ping_error=None):
        self.tick, self.ping_error = tick, ping_error

    async def ping(self):
        if self.ping_error:
            raise self.ping_error
        return True

    async def get(self, key):
        assert key == "melorin:worker:last_tick"
        return self.tick


async def test_worker_probe_without_redis(monkeypatch):
    monkeypatch.setattr(health, "get_redis", lambda: None)
    result = await health.probe_worker()
    assert (result.redis_ok, result.worker_ok, result.last_tick) == (False, False, None)


@pytest.mark.parametrize(
    ("age", "expected"),
    [(1, True), (14, True), (16, False), (-5, False)],
)
async def test_worker_probe_heartbeat_age(monkeypatch, age, expected):
    monkeypatch.setattr(health, "get_redis", lambda: _Redis(tick=str(time.time() - age)))
    result = await health.probe_worker()
    assert result.redis_ok is True
    assert result.worker_ok is expected


async def test_worker_probe_missing_tick_is_stale(monkeypatch):
    monkeypatch.setattr(health, "get_redis", lambda: _Redis(tick=None))
    result = await health.probe_worker()
    assert result.redis_ok is True and result.worker_ok is False


async def test_worker_probe_redis_error_marks_unavailable(monkeypatch):
    monkeypatch.setattr(health, "get_redis", lambda: _Redis(ping_error=ConnectionError("down")))
    result = await health.probe_worker()
    assert result.redis_ok is False and result.worker_ok is False


async def test_database_probe_failure_is_reported_not_raised(monkeypatch):
    def broken():
        raise RuntimeError("boom " * 100)

    monkeypatch.setattr(health, "session_factory", broken)
    result = await health.probe_database()
    assert result.ok is False and result.error and len(result.error) <= 200


def test_build_checks_shape_and_degraded_rate_limit():
    ok = build_checks(DatabaseProbe(ok=True, pending=3, unhealthy_panels=1), WorkerProbe(True, True, "1"))
    assert ok["database"] == "ok" and ok["rate_limit"] == "coordinated" and "database_error" not in ok
    bad = build_checks(DatabaseProbe(ok=False, error="x"), WorkerProbe())
    assert bad["database"] == "unavailable" and bad["redis"] == "unavailable"
    assert bad["rate_limit"] == "local_degraded" and bad["database_error"] == "x"


def test_publish_signals_thresholds(monkeypatch):
    alerts, gauges = {}, {}
    monkeypatch.setattr(health, "set_alert", lambda name, active, **kw: alerts.__setitem__(name, active))
    monkeypatch.setattr(health, "set_gauge", lambda name, value: gauges.__setitem__(name, value))
    health.publish_signals(DatabaseProbe(ok=True, pending=101, unhealthy_panels=2), WorkerProbe(True, False, None))
    assert alerts["MelorinOutboxBacklog"] is True and alerts["MelorinPanelsUnhealthy"] is True
    assert alerts["MelorinWorkerStale"] is True and alerts["MelorinDatabaseUnavailable"] is False
    assert gauges == {"melorin_outbox_pending": 101.0, "melorin_panels_unhealthy": 2.0}
    health.publish_signals(DatabaseProbe(ok=True, pending=100), WorkerProbe(True, True, "1"))
    assert alerts["MelorinOutboxBacklog"] is False
