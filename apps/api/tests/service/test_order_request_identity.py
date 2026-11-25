"""A checkout key must identify the complete request, not just its product."""

import itertools
import uuid

import pytest
from sqlalchemy import func, select

from _db import open_session, pg_url
from test_renewal_core import _world
from melorin.core import codes
from melorin.core.errors import AppError
from melorin.kernel.models.catalog import Coupon
from melorin.kernel.models.orders import Order
from melorin.kernel.models.wallet import Wallet
from melorin.modules.orders import service as orders


@pytest.fixture(autouse=True)
def _sqlite_order_numbers(monkeypatch):
    if pg_url() is None:
        numbers = itertools.count(1)

        async def next_code(session, sequence):
            return f"I{next(numbers):05d}"

        monkeypatch.setattr(codes, "next_code", next_code)


@pytest.mark.parametrize("field", ["coupon_code", "bundle_id", "selected_panel_id", "account_name", "payment_method"])
async def test_reused_key_rejects_different_checkout_details(field):
    async with open_session() as s:
        t = await _world(s)
        request = {"product_id": t.product.id, "bundle_id": t.bundle.id, "idempotency_key": "checkout-key"}
        first = await orders.create_order(s, t.ctx, **request)
        assert (await orders.create_order(s, t.ctx, **request)).id == first.id
        changed = {
            "coupon_code": "OTHER",
            "bundle_id": uuid.uuid4(),
            "selected_panel_id": uuid.uuid4(),
            "account_name": "other-name",
            "payment_method": "card",
        }
        with pytest.raises(AppError) as error:
            await orders.create_order(s, t.ctx, **{**request, field: changed[field]})
        assert (error.value.status, error.value.code) == (409, "IDEMPOTENCY_KEY_REUSE")
        assert (await s.get(Wallet, t.wallet_id)).balance == 48_000
        assert await s.scalar(select(func.count()).select_from(Order).where(Order.idempotency_key == "checkout-key")) == 1


async def test_coupon_replay_uses_coupon_normalization():
    async with open_session() as s:
        t = await _world(s)
        s.add(Coupon(code="SAVE", owner_key=str(t.store.id), store_id=t.store.id, scope="store", creator_type="admin", percent_bp=1000))
        await s.commit()
        request = {"product_id": t.product.id, "bundle_id": t.bundle.id, "idempotency_key": "coupon-key"}
        first = await orders.create_order(s, t.ctx, **request, coupon_code="save")
        replay = await orders.create_order(s, t.ctx, **request, coupon_code=" SAVE ")
        assert replay.id == first.id
        assert (await s.get(Wallet, t.wallet_id)).balance == 48_200


async def test_replay_uses_the_requested_bundle_not_the_resolved_default():
    async with open_session() as s:
        t = await _world(s)
        t.product.default_bundle_id = t.bundle.id
        await s.commit()
        request = {"product_id": t.product.id, "idempotency_key": "default-bundle-key"}
        first = await orders.create_order(s, t.ctx, **request)
        assert first.bundle_id == t.bundle.id
        t.product.default_bundle_id = None
        await s.commit()
        assert (await orders.create_order(s, t.ctx, **request)).id == first.id
        with pytest.raises(AppError) as error:
            await orders.create_order(s, t.ctx, **request, bundle_id=t.bundle.id)
        assert (error.value.status, error.value.code) == (409, "IDEMPOTENCY_KEY_REUSE")


async def test_legacy_order_without_request_identity_is_not_silently_replayed():
    async with open_session() as s:
        t = await _world(s)
        request = {"product_id": t.product.id, "bundle_id": t.bundle.id, "idempotency_key": "legacy-key"}
        first = await orders.create_order(s, t.ctx, **request)
        first.pricing_snapshot = {k: v for k, v in first.pricing_snapshot.items() if k != "checkout_request_v1"}
        await s.commit()
        with pytest.raises(AppError) as error:
            await orders.create_order(s, t.ctx, **request)
        assert (error.value.status, error.value.code) == (409, "IDEMPOTENCY_KEY_REUSE")
        assert (await s.get(Wallet, t.wallet_id)).balance == 48_000
