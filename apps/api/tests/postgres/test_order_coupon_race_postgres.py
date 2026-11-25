"""A coupon lock must not turn an idempotent checkout retry into a new failure."""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine, pg_url
from test_order_idempotency_postgres import _seed
from melorin.core.deps import StoreContext
from melorin.core.errors import AppError
from melorin.kernel.models.bundles import BundleProduct
from melorin.kernel.models.catalog import Coupon, CouponRedemption
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.stores import Store, StoreMembership
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction, Wallet
from melorin.modules.catalog import service as catalog
from melorin.modules.orders import service as orders

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL"),
]


@pytest.mark.parametrize(
    ("limit", "scenario"),
    [
        ("total", "same_key"),
        ("customer", "same_key"),
        ("total", "different_key"),
        ("total", "different_product"),
        ("total", "different_name"),
    ],
)
async def test_concurrent_coupon_checkout_replays_or_reports_the_real_conflict(monkeypatch, limit, scenario):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        ids = await _seed(factory)
        async with factory() as session:
            coupon = Coupon(
                code="ONCE",
                owner_key=str(ids["store"]),
                store_id=ids["store"],
                scope="store",
                creator_type="admin",
                percent_bp=1000,
                max_redemptions=1 if limit == "total" else None,
                per_customer_limit=1 if limit == "customer" else 99,
            )
            session.add(coupon)
            session.add(BundleProduct(bundle_id=ids["bundle"], product_id=ids["other_product"], is_listed=True, sort=1))
            await session.commit()
            coupon_id = coupon.id

        first_locked, second_waiting = asyncio.Event(), asyncio.Event()
        find_coupon = catalog.find_coupon

        async def synchronized_find(session, store, code, *, lock):
            if not lock:
                return await find_coupon(session, store, code, lock=lock)
            if asyncio.current_task().get_name() == "first-coupon":
                coupon = await find_coupon(session, store, code, lock=True)
                first_locked.set()
                await asyncio.wait_for(second_waiting.wait(), timeout=30)
                return coupon
            await asyncio.wait_for(first_locked.wait(), timeout=30)
            second_waiting.set()
            return await find_coupon(session, store, code, lock=True)

        monkeypatch.setattr(catalog, "find_coupon", synchronized_find)

        async def request(key, product, account_name=None):
            async with factory() as session:
                ctx = StoreContext(
                    store=await session.get(Store, ids["store"]),
                    user=await session.get(User, ids["user"]),
                    membership=await session.get(StoreMembership, ids["membership"]),
                )
                try:
                    order = await orders.create_order(
                        session,
                        ctx,
                        product_id=product,
                        bundle_id=ids["bundle"],
                        idempotency_key=key,
                        coupon_code="ONCE",
                        account_name=account_name,
                    )
                    return ("ok", order.id, order.status)
                except AppError as exc:
                    await session.rollback()
                    return ("error", exc.code)

        first = asyncio.create_task(request("coupon-race", ids["product"]), name="first-coupon")
        second = asyncio.create_task(
            request(
                "another-coupon-key" if scenario == "different_key" else "coupon-race",
                ids["other_product"] if scenario == "different_product" else ids["product"],
                "other-name" if scenario == "different_name" else None,
            ),
            name="second-coupon",
        )
        winner, follower = await asyncio.wait_for(asyncio.gather(first, second), timeout=45)
        assert winner[0] == "ok" and winner[2] == "paid"
        if scenario == "same_key":
            assert follower == winner
        elif scenario == "different_key":
            assert follower == ("error", "COUPON_EXHAUSTED")
        else:
            assert follower == ("error", "IDEMPOTENCY_KEY_REUSE")

        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(Order).where(Order.idempotency_key == "coupon-race")) == 1
            assert (await session.get(Wallet, ids["wallet"])).balance == 48_200
            assert (
                await session.scalar(select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.kind == "purchase")) == 1
            )
            assert await session.scalar(select(func.sum(LedgerEntry.amount))) == 0
            assert (await session.get(Coupon, coupon_id)).redemptions == 1
            assert await session.scalar(select(func.count()).select_from(CouponRedemption)) == 1
            assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.topic == "order.paid")) == 1
