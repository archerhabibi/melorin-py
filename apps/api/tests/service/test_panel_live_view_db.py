"""PanelLiveView (R1): the panel's numbers on screen, "temporarily unavailable" instead of an old number (decision 9)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine
from melorin.core import settings_store
from melorin.kernel.models.vpn import VpnAccount
from melorin.modules.vpn import inquiry, live
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError
from test_pasarguard_service_db import FakePanel, remote, seed

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def maker():
    live.clear_cache()
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)
    live.clear_cache()


def use(monkeypatch, fake):
    monkeypatch.setattr(live, "build_adapter", lambda panel: fake)
    monkeypatch.setattr(live, "seed_adapter", lambda adapter, account: adapter)


class _Down(FakePanel):
    async def get_account(self, username):
        raise PanelError(ErrorKind.TRANSIENT, "down")


class _Counting(FakePanel):
    async def get_account(self, username):
        self.single_calls += 1
        return self.users.get(username)


async def _page(s, ids):
    accounts = [await s.get(VpnAccount, i) for i in ids.values()]
    return accounts, [inquiry.account_out(a) for a in accounts]


async def test_flag_off_returns_the_page_untouched(maker, monkeypatch):
    _, ids = await seed(maker, ["u1"])
    use(monkeypatch, _Counting([remote("u1", used=5 * 2**30)]))
    async with maker() as s:
        await settings_store.set_value(s, live.SETTING, False)
        await s.commit()
        accounts, outs = await _page(s, ids)
        assert await live.overlay_page(s, outs, accounts) == outs  # switched off: no panel call


async def test_flag_is_on_by_default(maker, monkeypatch):
    _, ids = await seed(maker, ["u1"])
    use(monkeypatch, _Counting([remote("u1", used=5 * 2**30)]))
    async with maker() as s:
        accounts, outs = await _page(s, ids)
        (out,) = await live.overlay_page(s, outs, accounts)
        assert out.live is True and out.traffic_used_bytes == 5 * 2**30


async def test_flag_on_shows_the_panels_numbers_not_the_stored_copy(maker, monkeypatch):
    _, ids = await seed(maker, ["u1"])  # stored copy: 0 bytes used
    use(monkeypatch, FakePanel([remote("u1", used=5 * 2**30, limit=10 * 2**30, expire_days=12)]))
    async with maker() as s:
        await settings_store.set_value(s, live.SETTING, True)
        await s.commit()
        accounts, outs = await _page(s, ids)
        (out,) = await live.overlay_page(s, outs, accounts)
    assert out.live is True and out.traffic_used_bytes == 5 * 2**30 and out.usage_percent == 50
    assert out.days_left in (11, 12) and out.health == "active"


async def test_panel_down_shows_unavailable_and_no_old_number(maker, monkeypatch):
    _, ids = await seed(maker, ["u1"])
    async with maker() as s:
        acc = await s.get(VpnAccount, ids["u1"])
        acc.delivery_snapshot = {
            "subscription_url": "https://old/link",
            "links": [],
        }  # a stale delivery snapshot must not be shown as usage
        await settings_store.set_value(s, live.SETTING, True)
        await s.commit()
        use(monkeypatch, _Down([]))
        accounts, outs = await _page(s, ids)
        (out,) = await live.overlay_page(s, outs, accounts)
    assert out.live is False and out.live_note == live.UNAVAILABLE_NOTE
    assert out.traffic_used_bytes is None and out.usage_percent is None and out.days_left is None and out.health == "unavailable"


async def test_readings_are_cached_for_a_few_seconds(maker, monkeypatch):
    _, ids = await seed(maker, ["u1", "u2"])
    fake = _Counting([remote("u1"), remote("u2")])
    use(monkeypatch, fake)
    async with maker() as s:
        accounts = [await s.get(VpnAccount, i) for i in ids.values()]
        await live.read(s, accounts)
        await live.read(s, accounts)
        assert fake.single_calls == 2  # one read per account, the second page view came from the cache


async def test_account_missing_on_the_panel_is_unavailable_not_zero(maker, monkeypatch):
    _, ids = await seed(maker, ["u1"])
    use(monkeypatch, FakePanel([]))
    async with maker() as s:
        accounts = [await s.get(VpnAccount, i) for i in ids.values()]
        assert (await live.read(s, accounts))[accounts[0].id] is None
        assert not hasattr(VpnAccount, "traffic_used_bytes")  # nothing to write back: usage is not stored
