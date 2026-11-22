"""The reseller's website switch hides the public storefront only: its bot keeps working.

The reseller runner reads the store (id, bot texts) through ``/stores/by-slug/{slug}``. That route answers 404 to the public
while ``site_enabled`` is off (new resellers start that way), so it must still answer the runner (own secret, private network)
and must never open for somebody who came through the reverse proxy.
"""

from __future__ import annotations

import types

import pytest

from _db import make_store, make_user
from _http import api_client
from melorin.core import channel as ch

SECRETS = types.SimpleNamespace(
    is_dev=False,
    trusted_proxy_ips=["172.28.0.0/16"],
    store_web_url="https://main.example.com",
    public_api_url="https://main.example.com",
    bot_service_secret="s" * 40,
    main_bot_secret="m" * 40,
    reseller_bot_secret="r" * 40,
)


@pytest.fixture(autouse=True)
def _runner_secrets(monkeypatch):
    monkeypatch.setattr(ch, "get_settings", lambda: SECRETS)


async def _reseller(maker, *, site_enabled: bool):
    async with maker() as s:
        await make_store(s, kind="main")
        owner = await make_user(s)
        store = await make_store(s, kind="reseller", owner=owner, slug="shop-off")
        store.site_enabled = site_enabled
        store.bot_messages = {"welcome": "hello"}
        await s.commit()
        return str(store.id)


async def test_site_off_hides_the_store_from_the_public_but_not_from_its_bot_runner():
    async with api_client() as (client, maker, _main):
        store_id = await _reseller(maker, site_enabled=False)
        url = "/api/v1/stores/by-slug/shop-off"

        assert (await client.get(url)).status_code == 404  # the public sees no storefront
        assert (await client.get(url, headers={"X-Bot-Secret": "wrong" * 8})).status_code == 404  # an unknown secret opens nothing
        assert (await client.get(url, headers={"X-Bot-Secret": "m" * 40})).status_code == 404  # the MAIN runner may not read a reseller

        ok = await client.get(url, headers={"X-Bot-Secret": "r" * 40})  # the reseller runner, private network
        assert ok.status_code == 200
        assert ok.json()["id"] == store_id and ok.json()["bot_messages"] == {"welcome": "hello"}


async def test_a_request_through_the_proxy_never_gets_the_runner_exception():
    async with api_client() as (client, maker, _main):
        await _reseller(maker, site_enabled=False)
        r = await client.get("/api/v1/stores/by-slug/shop-off", headers={"X-Bot-Secret": "r" * 40, "X-Forwarded-For": "203.0.113.9"})
        assert r.status_code == 404


async def test_site_on_is_public_as_before():
    async with api_client() as (client, maker, _main):
        await _reseller(maker, site_enabled=True)
        assert (await client.get("/api/v1/stores/by-slug/shop-off")).status_code == 200
