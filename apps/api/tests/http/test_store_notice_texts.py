"""PG-06: a store words its own customer notices ({store}/{level} only); invalid wording is refused; platform text is the fallback."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import VpnAccount
from melorin.modules.vpn import notices
from test_pasarguard_service_db import seed

BASE = "/api/v1/admin"


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


def test_texts_are_validated():
    ok = notices.normalize_texts({"vpn_expired": {"title": " T ", "body": "B {store}"}})
    assert ok == {"vpn_expired": {"title": "T", "body": "B {store}"}}
    for bad in (
        None,
        [],
        {"nope": {"title": "a", "body": "b"}},
        {"vpn_expired": "x"},
        {"vpn_expired": {"title": "", "body": "b"}},
        {"vpn_expired": {"title": "a" * 81, "body": "b"}},
        {"vpn_expired": {"title": "a", "body": "b" * 501}},
    ):
        with pytest.raises(ValueError):
            notices.normalize_texts(bad)


def test_apply_texts_fills_only_known_placeholders_and_falls_back():
    st = {"texts": {"vpn_traffic_low": {"title": "{store}: low", "body": "{level}% used {0} {x}"}}}
    t, b = notices.apply_texts(st, "vpn_traffic_low", "T", "B", store_name="Shop", level=90)
    assert (t, b) == ("Shop: low", "90% used {0} {x}")  # no str.format(): unknown braces stay literal
    assert notices.apply_texts(st, "vpn_expired", "T", "B") == ("T", "B")
    assert notices.apply_texts({"texts": "junk"}, "vpn_expired", "T", "B") == ("T", "B")
    assert notices.apply_texts(None, "vpn_expired", "T", "B") == ("T", "B")


async def test_emitted_notice_uses_the_store_wording(maker):
    panel_id, ids = await seed(maker, ["u1"])
    async with maker() as s:
        store = (await s.scalars(select(Store))).first()
        store.vpn_notice_settings = {"texts": {"vpn_traffic_low": {"title": "{store} هشدار", "body": "{level} درصد"}}}
        acc = await s.get(VpnAccount, ids["u1"])
        await notices.traffic_low(s, acc, 90)
        await notices.expired(s, acc)  # no custom text -> platform text
        await s.commit()
        rows = (await s.scalars(select(OutboxEvent))).all()
    by_kind = {r.payload["kind"]: r.payload for r in rows if isinstance(r.payload, dict) and "kind" in r.payload}
    assert by_kind["vpn_traffic_low"]["body"] == "90 درصد"
    assert by_kind["vpn_traffic_low"]["title"].endswith("هشدار")
    assert by_kind["vpn_expired"]["title"] == "اکانت منقضی شد"


async def _login(c, m):
    await add_user(m, email="root@example.com", admin=True, totp=True)
    r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_texts_api_needs_admin_validates_and_round_trips():
    async with api_client() as (c, maker, main):
        url = f"{BASE}/stores/{main.id}/vpn-notice-texts"
        assert (await c.get(url)).status_code in (401, 403)
        h = await _login(c, maker)
        bad = await c.put(url, headers=h, json={"texts": {"bogus": {"title": "a", "body": "b"}}})
        assert bad.status_code == 422
        r = await c.put(url, headers=h, json={"texts": {"vpn_near_expiry": {"title": "x", "body": "y {store}"}}})
        assert r.status_code == 200 and list(r.json()["texts"]) == ["vpn_near_expiry"]
        assert (await c.get(url, headers=h)).json()["texts"]["vpn_near_expiry"]["body"] == "y {store}"
        # levels set earlier are not wiped by saving texts, and clearing texts keeps them
        lv = await c.put(f"{BASE}/stores/{main.id}/vpn-notices", headers=h, json={"traffic_low_levels": [70]})
        assert lv.status_code == 200
        cleared = await c.put(url, headers=h, json={"texts": {}})
        assert cleared.status_code == 200 and cleared.json()["texts"] == {}
        assert (await c.get(f"{BASE}/stores/{main.id}/vpn-notices", headers=h)).json()["traffic_low_levels"] == [70]
