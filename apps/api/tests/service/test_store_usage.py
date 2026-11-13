"""Per-store usage report: numbers come from the panel only, a silent panel shows no number, other stores' rows never leak."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, open_schema_engine
from melorin.kernel.models.vpn import Panel, PanelAdmin
from melorin.modules.panelops import store_usage
from melorin.modules.vpn.adapters.base import ErrorKind, PanelAccount, PanelError

pytestmark = pytest.mark.asyncio

NOW = dt.datetime(2026, 11, 8, 12, 0, tzinfo=dt.UTC)
GB = 2**30


def acct(name, *, used=0, limit=10 * GB, days=30, status="active", owner="rs_main", remote_status=None):
    return PanelAccount(
        ref=name,
        username=name,
        status=status,
        expire_at=None if days is None else NOW + dt.timedelta(days=days),
        traffic_limit_bytes=limit,
        traffic_used_bytes=used,
        remote_status=remote_status or status,
        owner=owner,
        # things the report must never pass on:
        subscription_url="https://sub.example.com/secret-token",
        links=["vless://secret"],
        online_at=NOW,
    )


class FakeListing:
    """A panel that lists users per admin like ``GET /api/users?admin=``: filtered, heaviest first, paged."""

    def __init__(self, users, *, ignore_filter=False, down=False):
        self.users, self.ignore_filter, self.down = list(users), ignore_filter, down
        self.calls = 0

    async def list_owner_accounts(self, owner, *, offset=0, limit=100, sort="-used_traffic"):
        self.calls += 1
        if self.down:
            raise PanelError(ErrorKind.TRANSIENT, "down")
        rows = self.users if self.ignore_filter else [u for u in self.users if u.owner == owner]
        rows = sorted(rows, key=lambda u: u.traffic_used_bytes, reverse=True)
        return rows[offset : offset + limit], len(rows)

    async def close(self):
        return None


@pytest.fixture
async def maker():
    store_usage.clear_cache()
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)
    store_usage.clear_cache()


async def _store_with_panels(maker, *names, admin_status="active"):
    """One reseller store with an active admin ``rs_main`` on each named panel."""
    async with maker() as s:
        store = await make_store(s, kind="reseller", slug="reseller-aaaa1111")
        panels = []
        for n in names:
            p = Panel(name=n, kind="pasarguard", base_url=f"https://{n}.example.com", is_enabled=True, config={})
            s.add(p)
            await s.flush()
            s.add(PanelAdmin(panel_id=p.id, store_id=store.id, username="rs_main", status=admin_status))
            panels.append(p)
        await s.commit()
        return store, panels


def use(monkeypatch, *fakes):
    queue = list(fakes)
    monkeypatch.setattr(store_usage, "build_adapter", lambda panel: queue.pop(0) if len(queue) > 1 else queue[0])


async def run(maker, store, **kw):
    async with maker() as s:
        return await store_usage.report(s, await s.get(type(store), store.id), now=NOW, **kw)


# --- the numbers -------------------------------------------------------------------------------------------------------
async def test_report_counts_states_usage_top_five_and_the_two_warnings(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1")
    users = [
        acct("u1", used=9 * GB),  # near exhaustion (90%)
        acct("u2", used=2 * GB, days=2),  # near expiry
        acct("u3", used=1 * GB),
        acct("u4", used=10 * GB, status="limited"),  # exhausted: counted as limited, not as "near"
        acct("u5", used=0, status="expired", days=-3),
        acct("u6", used=3 * GB, status="disabled"),
        acct("u7", used=0, status="active", remote_status="on_hold", days=None),
        acct("u8", used=5 * GB, limit=0),  # unlimited volume: never "near exhaustion"
    ]
    use(monkeypatch, FakeListing(users))
    rep = await run(maker, store)
    assert rep["live"] is True and rep["complete"] is True and rep["note"] is None
    assert rep["accounts"] == {"total": 8, "active": 4, "on_hold": 1, "limited": 1, "expired": 1, "disabled": 1, "other": 0}
    assert rep["usage"]["total_used_bytes"] == (9 + 2 + 1 + 10 + 0 + 3 + 0 + 5) * GB
    assert rep["near_exhaustion"] == 1 and rep["near_expiry"] == 1
    top = rep["top_consumers"]
    assert [t["username"] for t in top] == ["u4", "u1", "u8", "u6", "u2"] and len(top) == store_usage.TOP
    assert top[0]["percent"] == 100 and top[2]["limit_bytes"] == 0 and top[2]["percent"] is None


async def test_report_never_carries_ip_links_or_connection_details(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1")
    use(monkeypatch, FakeListing([acct("u1", used=GB)]))
    blob = json.dumps(await run(maker, store), default=str)
    for secret in ("secret-token", "vless://", "subscription", "online", "ip"):
        assert secret not in blob.replace("description", ""), secret


async def test_numbers_of_several_panels_are_added_up(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1", "p2")
    use(monkeypatch, FakeListing([acct("a", used=GB)]), FakeListing([acct("b", used=3 * GB), acct("c")]))
    rep = await run(maker, store)
    assert rep["accounts"]["total"] == 3 and rep["usage"]["total_used_bytes"] == 4 * GB
    assert [t["username"] for t in rep["top_consumers"]][:2] == ["b", "a"]
    assert [p["ok"] for p in rep["panels"]] == [True, True]


# --- panel silent: no number, not an old one ----------------------------------------------------------------------------
async def test_panel_down_shows_no_numbers_only_the_unavailable_note(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1")
    use(monkeypatch, FakeListing([acct("u1", used=GB)], down=True))
    rep = await run(maker, store)
    assert rep["live"] is False and rep["note"] == store_usage.UNAVAILABLE_NOTE
    assert "accounts" not in rep and "usage" not in rep and "top_consumers" not in rep
    assert rep["panels"] == [{"name": "p1", "ok": False}]


async def test_an_old_reading_is_not_served_after_the_panel_goes_down(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1")
    use(monkeypatch, FakeListing([acct("u1", used=GB)]))
    assert (await run(maker, store))["live"] is True
    use(monkeypatch, FakeListing([acct("u1", used=GB)], down=True))
    assert (await run(maker, store, fresh=True))["live"] is False


async def test_one_silent_panel_among_two_is_named_and_marks_the_numbers_incomplete(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1", "p2")
    use(monkeypatch, FakeListing([acct("a", used=GB)]), FakeListing([], down=True))
    rep = await run(maker, store)
    assert rep["live"] is True and rep["complete"] is False and rep["note"] == store_usage.PARTIAL_NOTE
    assert rep["accounts"]["total"] == 1 and rep["panels"] == [{"name": "p1", "ok": True}, {"name": "p2", "ok": False}]


# --- another store's rows must never appear -----------------------------------------------------------------------------
async def test_a_panel_that_ignores_the_admin_filter_is_discarded_not_shown(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1")
    users = [acct("mine", used=GB), acct("theirs", used=99 * GB, owner="rs_other")]
    use(monkeypatch, FakeListing(users, ignore_filter=True))
    rep = await run(maker, store)
    assert rep["live"] is False and "theirs" not in json.dumps(rep, default=str)


async def test_rows_without_a_shown_owner_cannot_be_verified_and_are_discarded(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1")
    use(monkeypatch, FakeListing([acct("x", owner=None)], ignore_filter=True))
    assert (await run(maker, store))["live"] is False


# --- scope and honesty --------------------------------------------------------------------------------------------------
async def test_a_scan_cut_at_the_limit_says_incomplete_but_keeps_the_exact_account_count(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1")
    monkeypatch.setattr(store_usage, "SCAN_LIMIT", 200)
    users = [acct(f"u{i}", used=i) for i in range(250)]
    fake = FakeListing(users)
    use(monkeypatch, fake)
    rep = await run(maker, store)
    assert rep["complete"] is False and rep["accounts"]["total"] == 250  # the panel's own count
    assert fake.calls == 2  # 2 pages of 100, then stop at the limit
    assert rep["top_consumers"][0]["username"] == "u249"  # heaviest first, so the top is still right


async def test_a_store_without_panel_admin_gets_an_honest_empty_report(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1", admin_status="pending")
    use(monkeypatch, FakeListing([acct("u1")]))
    rep = await run(maker, store)
    assert rep["live"] is True and rep["accounts"]["total"] == 0 and rep["panels"] == []


async def test_a_panel_without_per_store_admins_is_skipped(maker, monkeypatch):
    store, (panel,) = await _store_with_panels(maker, "p1")
    async with maker() as s:
        (await s.get(Panel, panel.id)).config = {"admin_per_store": False}
        await s.commit()
    fake = FakeListing([acct("u1")])
    use(monkeypatch, fake)
    rep = await run(maker, store)
    assert fake.calls == 0 and rep["accounts"]["total"] == 0


async def test_a_good_reading_is_reused_briefly(maker, monkeypatch):
    store, _ = await _store_with_panels(maker, "p1")
    fake = FakeListing([acct("u1")])
    use(monkeypatch, fake)
    await run(maker, store)
    await run(maker, store)
    assert fake.calls == 1
    await run(maker, store, fresh=True)
    assert fake.calls == 2
