"""R4 (traffic warnings from the panel's own numbers), R5 (analytics: last-known label + panel aggregates), R6 (admin list is live)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine
from melorin.core import settings_store
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.modules.reports import analytics
from melorin.modules.vpn import live, notices, sync
from test_panel_live_view_db import _Down, use
from test_pasarguard_phase1_db import NOW, FakePanel, remote, seed

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def maker():
    live.clear_cache()
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)
    live.clear_cache()


async def test_percent_of_uses_the_numbers_it_is_given():
    assert notices.percent_of(10 * 2**30, 9 * 2**30) == 90
    assert notices.percent_of(0, 5) is None  # unlimited package: no percent
    assert notices.percent_of(None, None) is None


async def test_traffic_warning_level_comes_from_the_panel_reading(maker):
    _, ids = await seed(maker, ["u1"])
    async with maker() as s:
        acc = await s.get(VpnAccount, ids["u1"])
        await sync.apply_remote(s, acc, remote("u1", used=9 * 2**30, limit=10 * 2**30), now=NOW)
        assert acc.traffic_notified_level == 90  # the panel said 90 %


async def test_admin_list_overlay_is_live_when_flag_on_and_unavailable_when_panel_down(maker, monkeypatch):
    _, ids = await seed(maker, ["u1"])
    row = {"id": ids["u1"], "status": "active", "traffic_used_bytes": 123, "days_left": 1, "health": "active"}
    async with maker() as s:
        acc = await s.get(VpnAccount, ids["u1"])
        await settings_store.set_value(s, live.SETTING, False)
        await s.commit()
        assert await live.overlay_rows(s, [row], [acc]) == [row]  # switched off: untouched, no panel call
        await settings_store.set_value(s, live.SETTING, True)
        await s.commit()
        use(monkeypatch, FakePanel([remote("u1", used=5 * 2**30, expire_days=12)]))
        (live_row,) = await live.overlay_rows(s, [row], [acc])
        assert live_row["live"] is True and live_row["traffic_used_bytes"] == 5 * 2**30
        live.clear_cache()
        use(monkeypatch, _Down([]))
        (down,) = await live.overlay_rows(s, [row], [acc])
        assert down["live"] is False and down["traffic_used_bytes"] is None and down["health"] == "unavailable"


async def test_analytics_snapshot_labels_sold_volume_and_reports_panel_numbers(maker):
    await seed(maker, ["u1"])
    async with maker() as s:
        panel = (await s.scalars(select(Panel))).one()
        panel.metrics_snapshot = {"up": True, "users_total": 5, "online_users": 2}
        panel.metrics_snapshot_at = NOW
        await s.commit()
        snap = await analytics._snapshot(s, NOW + dt.timedelta(minutes=1))
    vpn = snap["vpn"]
    assert vpn["traffic_source"] == "sold" and vpn["traffic_used_bytes"] is None  # no stored usage sum; usage is the panel's
    assert vpn["traffic_limit_bytes"] == 10 * 2**30  # the sold volume of the active account
    assert vpn["panels"] == [
        {"panel_id": str(panel.id), "name": "pg", "up": True, "users_total": 5, "online_users": 2, "taken_at": NOW.isoformat()}
    ]


# ---------------------------------------------------------------------------------------------------------------- PG-02 words
async def test_state_hint_says_what_on_hold_and_depleted_mean():
    from melorin.modules.vpn import inquiry

    note, action = inquiry.state_hint("on_hold", "active", can_renew=False)
    assert "اولین اتصال" in note and action is None
    note, action = inquiry.state_hint("limited", "depleted", can_renew=True)
    assert note == inquiry.DEPLETED_NOTE and action == "renew"
    assert inquiry.state_hint("limited", "depleted", can_renew=False) == (inquiry.DEPLETED_NOTE, None)
    assert inquiry.state_hint("active", "active", can_renew=True) == (None, None)
