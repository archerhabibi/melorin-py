"""Health, capacity and attention are three small models built from one source each."""

import datetime as dt
from types import SimpleNamespace

from melorin.domain.panel_snapshot import capacity_snapshot_of, issue_of, snapshot_of

NOW = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.UTC)


def _panel(**kw):
    base = dict(
        id="p1",
        name="main",
        health_status="healthy",
        health_detail={"sellable": True},
        last_health_at=NOW - dt.timedelta(minutes=1),
        last_health_error=None,
        metrics_snapshot={"up": True, "users_total": 7},
        metrics_snapshot_at=NOW - dt.timedelta(minutes=1),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_snapshot_exposes_a_health_view_without_the_reading():
    snap = snapshot_of(_panel())
    health = snap.health
    assert (health.panel_id, health.status, health.sellable, health.last_error) == ("p1", "healthy", True, None)
    assert health.is_fresh(NOW, dt.timedelta(minutes=5)) is True
    assert health.is_fresh(NOW, dt.timedelta(seconds=10)) is False
    assert snap.users_total == 7


def test_capacity_snapshot_free_is_never_negative():
    view = {
        "capacity": 100,
        "used": 130,
        "source": "panel",
        "panel_users_as_of": NOW,
        "state": "full",
        "percent": 130,
        "melorin_accounts": 90,
        "panel_users": 130,
    }
    cap = capacity_snapshot_of("s1", view)
    assert (cap.capacity, cap.used, cap.free, cap.source, cap.state) == (100, 130, 0, "panel", "full")
    assert capacity_snapshot_of("s2", {"capacity": 10, "used": 4}).free == 6


def test_operational_issue_needs_action_only_while_open():
    row = SimpleNamespace(kind="missing_on_panel", vpn_account_id="a1", status="open", occurrences=3, last_seen_at=NOW)
    issue = issue_of(row)
    assert issue.key == "missing_on_panel:a1" and issue.needs_action and issue.occurrences == 3
    row.status = "resolved"
    assert issue_of(row).needs_action is False
