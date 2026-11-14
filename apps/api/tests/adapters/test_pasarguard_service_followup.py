"""PasarGuard Phase 1 follow-up: per-store low-traffic levels (PG-06) and reconcile metrics (PG-04 #7)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core import health
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import ReconciliationIssue, VpnAccount
from melorin.modules.vpn_accounts import issues, notices
from test_pasarguard_service_db import NOW, FakePanel, remote, run, seed, use

BASE = "/api/v1/admin"
GIB = 2**30


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


# ------------------------------------------------------------------------------------------------------------ pure rules
def test_levels_are_validated_sorted_and_deduplicated():
    assert notices.normalize_levels([90, 50, 90]) == (50, 90)
    assert notices.normalize_levels([]) == ()
    assert notices.normalize_levels((1, 99)) == (1, 99)


@pytest.mark.parametrize("bad", ["80", None, 80, [0], [100], [-5], [80.5], ["80"], [True], [10, 20, 30, 40, 50]])
def test_bad_levels_are_refused(bad):
    with pytest.raises(ValueError):
        notices.normalize_levels(bad)


def test_a_store_without_settings_or_with_broken_ones_gets_the_defaults():
    assert notices.levels_for_store(None) == notices.TRAFFIC_LOW_LEVELS
    assert notices.levels_for_store({}) == notices.TRAFFIC_LOW_LEVELS
    assert notices.levels_for_store({"traffic_low_levels": "junk"}) == notices.TRAFFIC_LOW_LEVELS
    assert notices.levels_for_store({"traffic_low_levels": [60]}) == (60,)
    assert notices.levels_for_store({"traffic_low_levels": []}) == ()  # an explicit "no warnings" is respected


def test_traffic_level_uses_the_given_levels():
    assert notices.traffic_level(85) == 80
    assert notices.traffic_level(85, (50,)) == 50
    assert notices.traffic_level(95, ()) == 0
    assert notices.traffic_level(None, (50,)) == 0


# ------------------------------------------------------------------------------------------- reconcile uses the store's levels
async def _set_levels(maker, levels):
    async with maker() as s:
        store = (await s.scalars(select(Store))).first()
        store.vpn_notice_settings = None if levels is None else {"traffic_low_levels": levels}
        await s.commit()


async def _level(maker, account_id):
    async with maker() as s:
        return (await s.get(VpnAccount, account_id)).traffic_notified_level


async def test_a_store_with_its_own_level_is_warned_earlier_than_the_default(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1"])
    await _set_levels(maker, [50])
    use(monkeypatch, FakePanel([remote("u1", used=6 * GIB)]))  # 60% of 10 GiB
    await run(maker, panel_id)
    assert await _level(maker, ids["u1"]) == 50


async def test_the_default_store_is_not_warned_at_sixty_percent(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1"])
    use(monkeypatch, FakePanel([remote("u1", used=6 * GIB)]))
    await run(maker, panel_id)
    assert await _level(maker, ids["u1"]) == 0


async def test_a_store_can_switch_low_traffic_warnings_off(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1"])
    await _set_levels(maker, [])
    use(monkeypatch, FakePanel([remote("u1", used=int(9.8 * GIB))]))  # 98%: would warn at 80/90 by default
    await run(maker, panel_id)
    assert await _level(maker, ids["u1"]) == 0


async def test_each_level_warns_once_per_package(maker, monkeypatch):
    panel_id, ids = await seed(maker, ["u1"])
    await _set_levels(maker, [50, 90])
    fake = FakePanel([remote("u1", used=6 * GIB)])
    use(monkeypatch, fake)
    await run(maker, panel_id)
    assert await _level(maker, ids["u1"]) == 50
    await run(maker, panel_id)  # same usage again: no second warning, level unchanged
    assert await _level(maker, ids["u1"]) == 50
    fake.users["u1"] = remote("u1", used=int(9.5 * GIB))
    await run(maker, panel_id)
    assert await _level(maker, ids["u1"]) == 90


# ------------------------------------------------------------------------------------------------------------- admin API
async def _login(c, m):
    await add_user(m, email="root@example.com", admin=True, totp=True)
    r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_notice_settings_need_an_admin():
    async with api_client() as (c, _, main):
        for method in ("get", "put", "delete"):
            r = await getattr(c, method)(
                f"{BASE}/stores/{main.id}/vpn-notices", **({"json": {"traffic_low_levels": [70]}} if method == "put" else {})
            )
            assert r.status_code in (401, 403), (method, r.status_code)


async def test_notice_settings_round_trip_and_reset():
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        url = f"{BASE}/stores/{main.id}/vpn-notices"
        first = (await c.get(url, headers=h)).json()
        assert first["is_default"] is True and first["traffic_low_levels"] == [80, 90]
        put = await c.put(url, json={"traffic_low_levels": [90, 70, 70]}, headers=h)
        assert put.status_code == 200 and put.json()["traffic_low_levels"] == [70, 90] and put.json()["is_default"] is False
        assert (await c.get(url, headers=h)).json()["traffic_low_levels"] == [70, 90]
        off = (await c.put(url, json={"traffic_low_levels": []}, headers=h)).json()
        assert off["traffic_low_levels"] == [] and off["is_default"] is False  # "no warnings" is a real choice, not "unset"
        back = (await c.delete(url, headers=h)).json()
        assert back["is_default"] is True and back["traffic_low_levels"] == [80, 90]


async def test_notice_settings_refuse_bad_input_and_unknown_stores():
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        url = f"{BASE}/stores/{main.id}/vpn-notices"
        for bad in ([0], [100], [10, 20, 30, 40, 50], ["x"]):
            assert (await c.put(url, json={"traffic_low_levels": bad}, headers=h)).status_code == 422, bad
        missing = f"{BASE}/stores/00000000-0000-0000-0000-000000000009/vpn-notices"
        assert (await c.get(missing, headers=h)).status_code == 404
        assert (await c.put(missing, json={"traffic_low_levels": [70]}, headers=h)).status_code == 404
        assert (await c.get(url, headers=h)).json()["is_default"] is True  # nothing was stored by the refused calls


# ---------------------------------------------------------------------------------------------------------------- metrics
async def test_open_issues_are_counted_by_kind_and_lag_is_the_oldest_sync(maker):
    _, ids = await seed(maker, ["u1", "u2"])  # both synced two hours ago
    async with maker() as s:
        await issues.open_issue(s, ids["u1"], issues.MISSING, {}, now=NOW)
        await issues.open_issue(s, ids["u2"], issues.MISSING, {}, now=NOW)
        await issues.open_issue(s, ids["u2"], issues.OWNER_MISMATCH, {}, now=NOW)
        await s.commit()
    async with maker() as s:
        probe = health.DatabaseProbe()
        await health._probe_reconcile(s, probe)
    assert probe.open_issues == {issues.MISSING: 2, issues.OWNER_MISMATCH: 1}
    assert probe.reconcile_lag_seconds is not None and 2 * 3600 - 120 < probe.reconcile_lag_seconds < 2 * 3600 + 3600


async def test_lag_is_unknown_while_an_account_was_never_synced(maker):
    _, ids = await seed(maker, ["u1"])
    async with maker() as s:
        (await s.get(VpnAccount, ids["u1"])).last_synced_at = None
        await s.commit()
    async with maker() as s:
        probe = health.DatabaseProbe()
        await health._probe_reconcile(s, probe)
    assert probe.reconcile_lag_seconds is None  # a fresh install must not look like a 50-year lag


async def test_closed_issues_are_not_counted(maker):
    _, ids = await seed(maker, ["u1"])
    async with maker() as s:
        await issues.open_issue(s, ids["u1"], issues.MISSING, {}, now=NOW)
        await issues.close_issues(s, [ids["u1"]], [issues.MISSING], now=NOW)
        await s.commit()
    async with maker() as s:
        probe = health.DatabaseProbe()
        await health._probe_reconcile(s, probe)
        assert (await s.scalars(select(ReconciliationIssue))).first().status != "open"
    assert probe.open_issues == {}


def test_publish_signals_exports_every_issue_kind_even_at_zero(monkeypatch):
    gauges = {}
    monkeypatch.setattr(health, "set_alert", lambda *a, **k: None)
    monkeypatch.setattr(health, "set_gauge", lambda name, value, **labels: gauges.__setitem__((name, tuple(sorted(labels.items()))), value))
    health.publish_signals(
        health.DatabaseProbe(ok=True, open_issues={issues.MISSING: 3}, reconcile_lag_seconds=7200.0), health.WorkerProbe(True, True, "1")
    )
    for kind in health.ISSUE_KINDS:
        assert ("melorin_reconcile_open_issues", (("kind", kind),)) in gauges
    assert gauges[("melorin_reconcile_open_issues", (("kind", issues.MISSING),))] == 3.0
    assert gauges[("melorin_reconcile_open_issues", (("kind", issues.OWNER_MISMATCH),))] == 0.0
    assert gauges[("melorin_reconcile_lag_seconds", ())] == 7200.0
    gauges.clear()
    health.publish_signals(health.DatabaseProbe(ok=True), health.WorkerProbe(True, True, "1"))
    assert ("melorin_reconcile_lag_seconds", ()) not in gauges  # unknown lag is omitted, not published as 0
