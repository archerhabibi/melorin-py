"""Editing a coupon obeys the same rules as creating it, and a multi-store coupon is never paid by one reseller.

Part of docs/17-Referral-Coupon-Store-Scope.md: a discount code belongs to ONE store/agency (its owner decides and pays for it);
only the platform may run a promotion across several stores, and then the platform pays.
"""

from __future__ import annotations

import datetime as dt

from _db import make_product, make_store, make_user, open_session
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.kernel.models.catalog import Coupon, StoreProduct
from melorin.kernel.models.stores import ResellerProfile
from melorin.modules.catalog import service as catalog

AUTH = "/api/v1/auth"
V1 = "/api/v1"
_T0 = dt.datetime(2030, 1, 10, tzinfo=dt.UTC)


def _code(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


async def _login(c, email, **extra):
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD, **extra})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _world(c, maker):
    owner = await add_user(maker, email="a@example.com")
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    async with maker() as s:
        store = await make_store(s, kind="reseller", owner=owner, slug="shop-a")
        s.add(ResellerProfile(store_id=store.id, user_id=owner.id, debt_limit=5000, api_enabled=False, sales_enabled=True))
        await s.commit()
    return store, {"a": await _login(c, "a@example.com"), "root": await _login(c, "root@example.com", totp_code=totp_now())}


async def test_owner_cannot_edit_a_coupon_into_an_invalid_window():
    async with api_client() as (c, maker, main):
        store, h = await _world(c, maker)
        made = await c.post(
            f"{V1}/stores/{store.id}/coupons", headers=h["a"], json={"code": "WIN10", "percent_bp": 1000, "starts_at": _T0.isoformat()}
        )
        assert made.status_code == 201, made.text
        url = f"{V1}/stores/{store.id}/coupons/{made.json()['id']}"
        bad = await c.patch(url, headers=h["a"], json={"ends_at": (_T0 - dt.timedelta(days=1)).isoformat()})  # ends before it starts
        assert bad.status_code == 400 and _code(bad) == "COUPON_BAD_WINDOW"
        ok = await c.patch(url, headers=h["a"], json={"ends_at": (_T0 + dt.timedelta(days=5)).isoformat(), "max_discount": 700})
        assert ok.status_code == 200 and ok.json()["max_discount"] == 700


async def test_admin_edit_goes_through_the_same_rules_and_keeps_the_owner_store():
    async with api_client() as (c, maker, main):
        store, h = await _world(c, maker)
        made = await c.post(
            f"{V1}/admin/coupons",
            headers=h["root"],
            json={"code": "ADM20", "percent_bp": 2000, "scope": "store", "store_id": str(store.id), "starts_at": _T0.isoformat()},
        )
        assert made.status_code == 201, made.text
        url = f"{V1}/admin/coupons/{made.json()['id']}"
        bad = await c.patch(url, headers=h["root"], json={"ends_at": (_T0 - dt.timedelta(days=2)).isoformat()})
        assert bad.status_code == 400 and _code(bad) == "COUPON_BAD_WINDOW"
        ok = await c.patch(url, headers=h["root"], json={"status": "disabled"})
        assert ok.status_code == 200 and ok.json()["status"] == "disabled" and ok.json()["store_id"] == str(store.id)


async def test_admin_domain_coupon_must_be_platform_funded():
    async with api_client() as (c, maker, main):
        store, h = await _world(c, maker)
        base = {"code": "DOM30", "percent_bp": 1000, "scope": "domain", "allowed_store_ids": [str(store.id)]}
        bad = await c.post(f"{V1}/admin/coupons", headers=h["root"], json={**base, "funded_by": "store"})
        assert bad.status_code == 400 and _code(bad) == "COUPON_FUNDING_INVALID"
        ok = await c.post(f"{V1}/admin/coupons", headers=h["root"], json=base)  # the default funding is the platform
        assert ok.status_code == 201 and ok.json()["funded_by"] == "platform"


async def test_a_legacy_store_funded_domain_coupon_still_costs_the_reseller_nothing():
    """Rows written before the rule existed may say funded_by=store; at sale time a domain coupon is the platform's anyway."""
    async with open_session() as s:
        store = await make_store(s, kind="reseller", owner=await make_user(s))
        product = await make_product(s, price=10_000)
        sp = StoreProduct(store_id=store.id, product_id=product.id, is_enabled=True, customer_price=12_000)
        s.add(sp)
        domain = Coupon(code="OLD", owner_key="admin", scope="domain", funded_by="store", fixed=1000, currency="IRT", allowed_store_kinds=["reseller"])
        own = Coupon(code="OWN", owner_key=str(store.id), store_id=store.id, scope="store", funded_by="store", fixed=1000, currency="IRT")
        s.add_all([domain, own])
        await s.commit()
        q_domain = await catalog.build_quote(s, store, product, sp, domain, 1000, main_currency="IRT")
        q_own = await catalog.build_quote(s, store, product, sp, own, 1000, main_currency="IRT")
        assert q_domain.coupon_funded_by == "platform" and q_domain.reseller_cost == 9_000  # the platform absorbs it
        assert q_own.coupon_funded_by == "store" and q_own.reseller_cost == 10_000  # his own coupon is his own cost
