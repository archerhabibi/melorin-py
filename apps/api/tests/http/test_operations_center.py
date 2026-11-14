"""Operations Center: /admin/dashboard carries one roll-up of everything waiting for an admin (read-only aggregate)."""

from __future__ import annotations

from _db import make_order, make_product, make_store, make_user
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.modules.admin.operations_center import QUEUES

AUTH = "/api/v1/auth"
ADMIN = "/api/v1/admin"


async def _admin(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post(f"{AUTH}/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_dashboard_attention_lists_every_queue_with_zero_on_an_empty_system():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        body = (await c.get(f"{ADMIN}/dashboard", headers=h)).json()
    att = body["attention"]
    assert att["total"] == 0
    assert [i["key"] for i in att["items"]] == list(QUEUES)
    assert all(i["count"] == 0 and i["section"] for i in att["items"])


async def test_dashboard_attention_counts_failed_provisioning_and_pending_refunds():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        async with maker() as s:
            store, product = await make_store(s), await make_product(s)
            user = await make_user(s)
            await make_order(s, user=user, store=store, product=product, status="provisioning_failed")
            await make_order(s, user=user, store=store, product=product, status="manual_review")
            await make_order(s, user=user, store=store, product=product, status="refund_pending")
            await make_order(s, user=user, store=store, product=product, status="completed")
            await s.commit()
        att = (await c.get(f"{ADMIN}/dashboard", headers=h)).json()["attention"]
    by = {i["key"]: i["count"] for i in att["items"]}
    assert by["provisioning_failures"] == 2
    assert by["refunds_pending"] == 1
    assert att["total"] == 3
