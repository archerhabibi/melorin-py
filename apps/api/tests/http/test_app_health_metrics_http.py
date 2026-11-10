"""Phase 4: the app shell over HTTP - liveness (GET+HEAD), readiness (200/503, detail only for operators) and /metrics
(dev open, production bearer-only, Redis/DB failures never break the scrape)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import melorin.app as app_module
import melorin.core.redis as redis_module
from _http import api_client


@pytest.fixture
def prod(monkeypatch):
    """Switch the app module's settings to production-like auth for the operator endpoints."""
    settings = app_module.s.model_copy(update={"env": "production", "health_token": "h" * 40, "metrics_token": "m" * 40})
    monkeypatch.setattr(app_module, "s", settings)
    return settings


def _probes(monkeypatch, *, db=True, redis=True, worker=True):
    async def probe_db():
        return SimpleNamespace(ok=db)

    async def probe_wk():
        return SimpleNamespace(redis_ok=redis, worker_ok=worker)

    monkeypatch.setattr(app_module, "probe_database", probe_db)
    monkeypatch.setattr(app_module, "probe_worker", probe_wk)
    monkeypatch.setattr(app_module, "publish_signals", lambda *_: None)
    monkeypatch.setattr(app_module, "build_checks", lambda d, w: {"checks": {"database": d.ok, "redis": w.redis_ok, "worker": w.worker_ok}})


# --- liveness --------------------------------------------------------------------------------------------------------


async def test_liveness_answers_get_and_head_on_both_paths():
    async with api_client(with_main_store=False) as (c, _, _):
        for path in ("/health/live", "/healthz"):
            g = await c.get(path)
            assert g.status_code == 200 and g.json()["status"] == "ok"
            h = await c.head(path)
            assert h.status_code == 200 and h.content == b""  # uptime monitors probe with HEAD


async def test_openapi_version_reports_the_app_version():
    async with api_client(with_main_store=False) as (c, _, _):
        r = await c.get("/openapi-version")
        assert r.status_code == 200 and r.json() == {"version": app_module.app.version}


# --- readiness -------------------------------------------------------------------------------------------------------


async def test_ready_is_200_when_every_dependency_is_up_and_details_are_open_in_development(monkeypatch):
    _probes(monkeypatch)
    async with api_client(with_main_store=False) as (c, _, _):
        for path in ("/health/ready", "/health"):
            r = await c.get(path)
            assert r.status_code == 200
            assert r.json() == {"status": "ready", "checks": {"database": True, "redis": True, "worker": True}}


@pytest.mark.parametrize("down", ["db", "redis", "worker"])
async def test_ready_is_503_when_any_single_dependency_is_down(monkeypatch, down):
    _probes(monkeypatch, db=down != "db", redis=down != "redis", worker=down != "worker")
    async with api_client(with_main_store=False) as (c, _, _):
        r = await c.get("/health/ready")
        assert r.status_code == 503 and r.json()["status"] == "not_ready"


async def test_ready_hides_dependency_detail_in_production_unless_the_health_token_is_sent(monkeypatch, prod):
    _probes(monkeypatch, worker=False)
    async with api_client(with_main_store=False) as (c, _, _):
        anon = await c.get("/health/ready")
        assert anon.status_code == 503 and anon.json() == {"status": "not_ready"}  # no topology leak to the internet
        wrong = await c.get("/health/ready", headers={"X-Melorin-Health-Token": "x" * 40})
        assert wrong.json() == {"status": "not_ready"}
        ok = await c.get("/health/ready", headers={"X-Melorin-Health-Token": prod.health_token})
        assert ok.status_code == 503 and ok.json()["checks"]["worker"] is False


# --- metrics ---------------------------------------------------------------------------------------------------------


class FakeRedis:
    def __init__(self, tick=None, boom=False):
        self.tick, self.boom = tick, boom

    async def get(self, key):
        assert key == "melorin:worker:last_tick"
        if self.boom:
            raise ConnectionError("redis down")
        return self.tick


async def test_metrics_requires_the_bearer_token_in_production(monkeypatch, prod):
    monkeypatch.setattr(redis_module, "get_redis", lambda: None)
    async with api_client(with_main_store=False) as (c, _, _):
        assert (await c.get("/metrics")).status_code == 401
        assert (await c.get("/metrics", headers={"Authorization": "Bearer nope"})).status_code == 401
        ok = await c.get("/metrics", headers={"Authorization": f"Bearer {prod.metrics_token}"})
        assert ok.status_code == 200 and ok.headers["content-type"].startswith("text/plain; version=0.0.4")


async def test_metrics_flags_a_missing_redis_and_a_stale_worker(monkeypatch):
    monkeypatch.setattr(redis_module, "get_redis", lambda: None)
    async with api_client(with_main_store=False) as (c, _, _):
        body = (await c.get("/metrics")).text
        assert "MelorinRedisUnavailable" in body and "MelorinWorkerStale" in body


async def test_metrics_reports_a_fresh_worker_heartbeat_as_healthy(monkeypatch):
    import time

    monkeypatch.setattr(redis_module, "get_redis", lambda: FakeRedis(tick=str(time.time())))
    async with api_client(with_main_store=False) as (c, _, _):
        r = await c.get("/metrics")
        assert r.status_code == 200 and "melorin_worker_last_tick" in r.text


async def test_metrics_scrape_survives_a_redis_error_and_a_business_metrics_failure(monkeypatch):
    monkeypatch.setattr(redis_module, "get_redis", lambda: FakeRedis(boom=True))

    async def broken_collect(session):
        raise RuntimeError("db gone")

    import melorin.modules.reports.business_metrics as bm

    monkeypatch.setattr(bm, "collect", broken_collect)
    async with api_client(with_main_store=False) as (c, _, _):
        r = await c.get("/metrics")
        assert r.status_code == 200  # a broken dependency must not break the scrape; the alerts carry the signal
        assert "MelorinRedisUnavailable" in r.text
