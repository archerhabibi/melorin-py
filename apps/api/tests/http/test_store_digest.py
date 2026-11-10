"""PG-06: opt-in daily digest for a store owner; Melorin-owned facts only; one per day; nothing to say = nothing sent."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.db import utcnow
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.vpn import VpnAccount
from melorin.modules.vpn import digest, notices
from test_pasarguard_phase1_db import seed


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


async def _digests(maker):
    async with maker() as s:
        return [r for r in (await s.scalars(select(OutboxEvent))).all() if (r.payload or {}).get("kind") == "vpn_daily_digest"]


async def _prep(maker, *, opt_in=True, owner=True):
    _, ids = await seed(maker, ["u1"])
    async with maker() as s:
        store = (await s.scalars(select(Store))).first()
        if owner:
            owner_user = await add_user(maker, email="own@example.com")
            store.owner_user_id = owner_user.id
        store.vpn_notice_settings = {"daily_digest": True} if opt_in else None
        await notices.expired(s, await s.get(VpnAccount, ids["u1"]))
        await s.commit()
    return ids


async def test_opted_in_store_gets_one_digest_per_day_with_only_melorin_facts(maker):
    await _prep(maker)
    async with maker() as s:
        assert await digest.run(s) == 1
        await s.commit()
    async with maker() as s:
        assert await digest.run(s) == 0  # same day: deduplicated
    rows = await _digests(maker)
    assert len(rows) == 1
    body = rows[0].payload["body"]
    assert "منقضی‌شده" in body and "GiB" not in body and "حجم مصرف" not in body  # no usage/expiry numbers in it


async def test_default_off_no_owner_and_empty_day_send_nothing(maker):
    await _prep(maker, opt_in=False)
    async with maker() as s:
        assert await digest.run(s) == 0
    async with maker() as s:  # opted in but nothing in the last 24h
        store = (await s.scalars(select(Store))).first()
        store.vpn_notice_settings = {"daily_digest": True}
        assert await digest.build(s, store, now=utcnow().replace(year=utcnow().year + 1)) is None


async def test_no_owner_means_no_digest(maker):
    await _prep(maker, owner=False)
    async with maker() as s:
        assert await digest.run(s) == 0


async def test_digest_switch_api():
    async with api_client() as (c, m, main):
        url = f"/api/v1/admin/stores/{main.id}/vpn-digest"
        assert (await c.put(url, json={"enabled": True})).status_code in (401, 403)
        await add_user(m, email="root@example.com", admin=True, totp=True)
        r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        ok = await c.put(url, headers=h, json={"enabled": True})
        assert ok.status_code == 200 and ok.json()["daily_digest"] is True
        async with m() as s:
            assert digest.enabled((await s.get(Store, main.id)).vpn_notice_settings)
