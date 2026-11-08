"""Owner-side subscription branding over HTTP: validated, owner-only, own store only, and the generic patch cannot touch it."""

from __future__ import annotations

import pytest

from _http import api_client
from test_panel_admins_http import _owner_headers, _world

pytestmark = pytest.mark.asyncio


def _url(store, tail="sub-branding"):
    return f"/api/v1/stores/{store.id}/reseller/{tail}"


async def test_owner_saves_validated_fields_and_nothing_unsafe(monkeypatch):
    async with api_client() as (c, maker, _):
        owner, reseller, other_owner, _, _ = await _world(maker)
        h = _owner_headers(owner, reseller)
        assert (await c.get(_url(reseller))).status_code == 401
        assert (await c.put(_url(reseller), json={"display_name": "A"}, headers=_owner_headers(other_owner, reseller))).status_code == 403
        r = await c.put(
            _url(reseller), json={"display_name": "Arash VPN", "support_url": "https://t.me/arash", "logo_url": "https://cdn.example.com/a.png"}, headers=h
        )
        assert r.status_code == 200, r.text
        assert (await c.get(_url(reseller), headers=h)).json()["fields"]["display_name"] == "Arash VPN"
        for bad in ({"display_name": "<b>x</b>"}, {"support_url": "http://insecure.example.com"}, {"logo_url": "https://x.example.com/p.html"}):
            assert (await c.put(_url(reseller), json=bad, headers=h)).status_code == 422
        assert (await c.get(_url(reseller), headers=h)).json()["fields"]["display_name"] == "Arash VPN"  # a refused save changes nothing


async def test_generic_branding_patch_cannot_set_or_wipe_the_subscription_block():
    async with api_client() as (c, maker, _):
        owner, reseller, *_ = await _world(maker)
        h = _owner_headers(owner, reseller)
        await c.put(_url(reseller), json={"display_name": "Keep me"}, headers=h)
        r = await c.patch(_url(reseller, "branding"), json={"branding": {"colors": {"a": "b"}, "sub": {"display_name": "<x>"}}}, headers=h)
        assert r.status_code == 200, r.text
        assert (await c.get(_url(reseller), headers=h)).json()["fields"] == {"display_name": "Keep me"}
        r2 = await c.patch(_url(reseller, "branding"), json={"branding": {}}, headers=h)  # replaces the rest, keeps the block
        assert r2.status_code == 200
        assert (await c.get(_url(reseller), headers=h)).json()["fields"] == {"display_name": "Keep me"}
