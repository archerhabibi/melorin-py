"""Discount codes stay inside the store/agency they were made for (docs/17-Referral-Coupon-Store-Scope.md)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from _db import make_product, make_store, make_user, open_session
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.errors import AppError
from melorin.domain.coupon import CouponError, CouponRule, CouponUse, evaluate
from melorin.kernel.models.catalog import Coupon, StoreProduct
from melorin.kernel.models.stores import ResellerProfile
from melorin.modules.catalog import service as catalog

AUTH = "/api/v1/auth"
V1 = "/api/v1"


def _code(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


# ------------------------------------------------------------------ pure rules
def _use(**over):
    base = dict(store_id="a", store_kind="reseller", product_id="p", amount=10_000, currency="IRT")
    base.update(over)
    return CouponUse(**base)


def test_a_store_coupon_is_invisible_to_every_other_store():
    rule = CouponRule(code="SAVE", scope="store", store_id="a", percent_bp=1000)
    assert evaluate(rule, _use(store_id="a")) == 1000
    with pytest.raises(CouponError) as exc:
        evaluate(rule, _use(store_id="b"))
    assert exc.value.code == "COUPON_INVALID"


def test_a_reseller_can_never_widen_a_coupon_beyond_his_store():
    from melorin.domain.coupon import validate_definition

    for over in ({"scope": "domain", "allowed_store_kinds": ("reseller",)}, {"store_id": "other"}):
        with pytest.raises(CouponError) as exc:
            validate_definition(
                CouponRule(code="X", creator_type="reseller", percent_bp=500, **{"store_id": "a", **over}), creator_store_id="a"
            )
        assert exc.value.code == "COUPON_SCOPE_FORBIDDEN"


def test_a_fixed_domain_coupon_never_applies_in_a_store_of_another_currency():
    rule = CouponRule(code="ALL", scope="domain", creator_type="admin", allowed_store_kinds=("reseller",), fixed=5000, currency="IRT")
    assert evaluate(rule, _use(store_id="z", currency="IRT")) == 5000
    with pytest.raises(CouponError) as exc:
        evaluate(rule, _use(store_id="z", currency="USD"))
    assert exc.value.code == "COUPON_NOT_APPLICABLE"


def test_the_window_quota_and_cap_still_hold_per_store_coupon():
    now = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
    rule = CouponRule(code="S", store_id="a", percent_bp=5000, max_discount=300, ends_at=now + dt.timedelta(days=1), max_redemptions=1)
    assert evaluate(rule, _use(now=now)) == 300  # capped
    with pytest.raises(CouponError) as exc:
        evaluate(CouponRule(code="S", store_id="a", percent_bp=5000, redemptions=1, max_redemptions=1), _use(now=now))
    assert exc.value.code == "COUPON_EXHAUSTED"


# ------------------------------------------------------------------ products must belong to the store
async def test_check_coupon_products_demands_products_the_reseller_store_really_sells():
    async with open_session() as s:
        main = await make_store(s, kind="main")
        store = await make_store(s, kind="reseller", owner=await make_user(s))
        sold, unsold = await make_product(s), await make_product(s)
        s.add(StoreProduct(store_id=store.id, product_id=sold.id, is_enabled=True))
        s.add(StoreProduct(store_id=store.id, product_id=unsold.id, is_enabled=False))  # switched off by Admin
        await s.commit()
        await catalog.check_coupon_products(s, store, [sold.id])
        await catalog.check_coupon_products(s, store, None)
        await catalog.check_coupon_products(s, main, [sold.id, unsold.id])  # the main store sells the catalogue itself
        for ids, code in (([unsold.id], "COUPON_PRODUCT_NOT_IN_STORE"), ([sold.id, unsold.id], "COUPON_PRODUCT_NOT_IN_STORE")):
            with pytest.raises(AppError) as exc:
                await catalog.check_coupon_products(s, store, ids)
            assert exc.value.code == code
        with pytest.raises(AppError) as exc:
            await catalog.check_coupon_products(s, store, ["00000000-0000-0000-0000-000000000001"])
        assert exc.value.code == "COUPON_PRODUCT_NOT_FOUND"


# ------------------------------------------------------------------ HTTP
async def _login(c, email, **extra):
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD, **extra})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _world(c, maker):
    owner_a = await add_user(maker, email="a@example.com")
    owner_b = await add_user(maker, email="b@example.com")
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    async with maker() as s:
        store_a = await make_store(s, kind="reseller", owner=owner_a, slug="shop-a")
        store_b = await make_store(s, kind="reseller", owner=owner_b, slug="shop-b", currency="IRR")
        for st, owner in ((store_a, owner_a), (store_b, owner_b)):
            s.add(ResellerProfile(store_id=st.id, user_id=owner.id, debt_limit=5000, api_enabled=False, sales_enabled=True))
        sold, unsold = await make_product(s), await make_product(s)
        s.add(StoreProduct(store_id=store_a.id, product_id=sold.id, is_enabled=True))
        await s.commit()
    h = {"a": await _login(c, "a@example.com"), "b": await _login(c, "b@example.com")}
    h["root"] = await _login(c, "root@example.com", totp_code=totp_now())
    return store_a, store_b, sold, unsold, h


async def test_owner_coupon_may_name_only_products_his_store_sells():
    async with api_client() as (c, maker, main):
        store_a, store_b, sold, unsold, h = await _world(c, maker)
        bad = await c.post(
            f"{V1}/stores/{store_a.id}/coupons", headers=h["a"], json={"code": "BAD10", "percent_bp": 1000, "product_ids": [str(unsold.id)]}
        )
        assert bad.status_code == 400 and _code(bad) == "COUPON_PRODUCT_NOT_IN_STORE"
        ok = await c.post(
            f"{V1}/stores/{store_a.id}/coupons", headers=h["a"], json={"code": "OK10", "percent_bp": 1000, "product_ids": [str(sold.id)]}
        )
        assert ok.status_code == 201 and ok.json()["store_id"] == str(store_a.id) and ok.json()["currency"] == "IRT"
        assert ok.json()["funded_by"] == "store"  # a reseller's coupon is never funded by the platform


async def test_owner_b_cannot_see_change_or_use_store_a_coupons():
    async with api_client() as (c, maker, main):
        store_a, store_b, sold, unsold, h = await _world(c, maker)
        made = await c.post(f"{V1}/stores/{store_a.id}/coupons", headers=h["a"], json={"code": "ONLYA", "percent_bp": 1000})
        coupon_id = made.json()["id"]
        # B cannot reach A's coupon routes at all ...
        assert (await c.get(f"{V1}/stores/{store_a.id}/coupons", headers=h["b"])).status_code == 403
        assert (
            await c.patch(f"{V1}/stores/{store_a.id}/coupons/{coupon_id}", headers=h["b"], json={"status": "disabled"})
        ).status_code == 403
        # ... and cannot reach it through his OWN store's route either (404, indistinguishable from a missing id)
        assert (
            await c.patch(f"{V1}/stores/{store_b.id}/coupons/{coupon_id}", headers=h["b"], json={"status": "disabled"})
        ).status_code == 404
        assert (await c.get(f"{V1}/stores/{store_b.id}/coupons", headers=h["b"])).json() == []
        # the same code is free to exist in store B with its own life
        same = await c.post(f"{V1}/stores/{store_b.id}/coupons", headers=h["b"], json={"code": "ONLYA", "percent_bp": 500})
        assert same.status_code == 201 and same.json()["id"] != coupon_id and same.json()["currency"] == "IRR"
        async with maker() as s:
            assert (await s.get(Coupon, uuid.UUID(coupon_id))).status == "active"


async def test_admin_store_coupon_is_pinned_to_an_existing_store_and_its_currency():
    async with api_client() as (c, maker, main):
        store_a, store_b, sold, unsold, h = await _world(c, maker)
        body = {"code": "ADM10", "percent_bp": 1000, "scope": "store", "store_id": str(store_b.id)}
        pinned = await c.post(f"{V1}/admin/coupons", headers=h["root"], json=body)
        assert pinned.status_code == 201 and pinned.json()["currency"] == "IRR"  # the store's currency, even though none was sent
        wrong = await c.post(f"{V1}/admin/coupons", headers=h["root"], json={**body, "code": "ADM11", "currency": "USD"})
        assert wrong.status_code == 400 and _code(wrong) == "COUPON_CURRENCY_MISMATCH"
        ghost = await c.post(
            f"{V1}/admin/coupons", headers=h["root"], json={**body, "code": "ADM12", "store_id": "00000000-0000-0000-0000-000000000001"}
        )
        assert ghost.status_code == 404
        foreign = await c.post(
            f"{V1}/admin/coupons",
            headers=h["root"],
            json={**body, "code": "ADM13", "store_id": str(store_a.id), "product_ids": [str(unsold.id)]},
        )
        assert foreign.status_code == 400 and _code(foreign) == "COUPON_PRODUCT_NOT_IN_STORE"


async def test_admin_domain_coupon_validates_its_allowed_stores_and_kinds():
    async with api_client() as (c, maker, main):
        store_a, store_b, sold, unsold, h = await _world(c, maker)
        base = {"code": "DOM10", "percent_bp": 1000, "scope": "domain"}
        ghost = await c.post(
            f"{V1}/admin/coupons", headers=h["root"], json={**base, "allowed_store_ids": ["00000000-0000-0000-0000-000000000001"]}
        )
        assert ghost.status_code == 400 and _code(ghost) == "COUPON_SCOPE_FORBIDDEN"
        kind = await c.post(f"{V1}/admin/coupons", headers=h["root"], json={**base, "allowed_store_kinds": ["galaxy"]})
        assert kind.status_code == 400 and _code(kind) == "COUPON_SCOPE_FORBIDDEN"
        ok = await c.post(f"{V1}/admin/coupons", headers=h["root"], json={**base, "allowed_store_ids": [str(store_a.id)]})
        assert ok.status_code == 201 and ok.json()["allowed_store_ids"] == [str(store_a.id)]
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(Coupon)) == 1
