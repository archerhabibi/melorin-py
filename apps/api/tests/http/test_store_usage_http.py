"""The owner's usage report over HTTP: only the caller's own store, owner-only, and honest when the panel is silent."""

from __future__ import annotations

import pytest

from _http import api_client
from melorin.modules.panelops import store_usage
from test_panel_admins_http import _owner_headers, _world
from test_store_usage import FakeListing, acct, GB

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fresh_cache():
    store_usage.clear_cache()
    yield
    store_usage.clear_cache()


def _url(store):
    return f"/api/v1/stores/{store.id}/reseller/usage-report"


def _use(monkeypatch, fake):
    monkeypatch.setattr(store_usage, "build_adapter", lambda panel: fake)


async def test_owner_sees_only_the_accounts_of_his_own_store(monkeypatch):
    async with api_client() as (c, maker, _):
        owner, reseller, other_owner, neighbour, _ = await _world(maker)
        _use(
            monkeypatch,
            FakeListing(
                [
                    acct("mine1", used=2 * GB, owner="rs_aaaa1111"),
                    acct("mine2", used=1 * GB, owner="rs_aaaa1111"),
                    acct("neighbour1", used=50 * GB, owner="rs_bbbb2222"),
                ]
            ),
        )
        r = await c.get(_url(reseller), headers=_owner_headers(owner, reseller))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["live"] is True and body["accounts"]["total"] == 2
        assert [t["username"] for t in body["top_consumers"]] == ["mine1", "mine2"]
        assert "neighbour1" not in r.text and "rs_bbbb2222" not in r.text
        # and the neighbour's own report is its own
        r2 = await c.get(_url(neighbour), headers=_owner_headers(other_owner, neighbour))
        assert [t["username"] for t in r2.json()["top_consumers"]] == ["neighbour1"]


async def test_only_the_owner_can_open_it(monkeypatch):
    async with api_client() as (c, maker, _):
        owner, reseller, other_owner, _, _ = await _world(maker)
        _use(monkeypatch, FakeListing([acct("mine1", owner="rs_aaaa1111")]))
        assert (await c.get(_url(reseller))).status_code == 401
        assert (await c.get(_url(reseller), headers=_owner_headers(other_owner, reseller))).status_code == 403


async def test_a_silent_panel_gives_the_unavailable_text_and_no_numbers(monkeypatch):
    async with api_client() as (c, maker, _):
        owner, reseller, _, _, _ = await _world(maker)
        _use(monkeypatch, FakeListing([acct("mine1", used=GB, owner="rs_aaaa1111")], down=True))
        r = await c.get(_url(reseller), headers=_owner_headers(owner, reseller))
        assert r.status_code == 200
        assert r.json()["live"] is False and r.json()["note"]
        assert "accounts" not in r.json() and "usage" not in r.json()
