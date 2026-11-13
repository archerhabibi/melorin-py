import datetime as dt
from types import SimpleNamespace as NS

from melorin.domain.panel_snapshot import snapshot_of

NOW = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.UTC)


def _panel(**kw):
    base = dict(id="p1", name="P", health_status="healthy", last_health_at=NOW, last_health_error=None, health_detail=None,
                metrics_snapshot=None, metrics_snapshot_at=None)
    base.update(kw)
    return NS(**base)


def test_sellable_follows_state_unless_detail_says_otherwise():
    assert snapshot_of(_panel()).sellable is True
    assert snapshot_of(_panel(health_status="unhealthy")).sellable is False
    assert snapshot_of(_panel(health_status="degraded", health_detail={"sellable": False})).sellable is False


def test_reading_accessors_and_freshness():
    s = snapshot_of(_panel(metrics_snapshot={"up": 1, "users_total": 7, "online_users": 2}, metrics_snapshot_at=NOW))
    assert (s.up, s.users_total, s.online_users) == (True, 7, 2)
    assert s.is_fresh(NOW + dt.timedelta(minutes=3), dt.timedelta(minutes=5))
    assert not s.is_fresh(NOW + dt.timedelta(minutes=9), dt.timedelta(minutes=5))


def test_no_reading_means_unknown_not_down():
    s = snapshot_of(_panel(metrics_snapshot={}))
    assert s.up is None and s.users_total is None and not s.is_fresh(NOW, dt.timedelta(minutes=5))
