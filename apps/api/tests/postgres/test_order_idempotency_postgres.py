"""Exercise order retries with independent sessions and real PostgreSQL locks."""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine, pg_url
from test_renewal_core import _world
from melorin.core import codes
from melorin.core.deps import StoreContext
from melorin.core.errors import AppError
from melorin.core.scope import StoreScope
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.stores import Store, StoreMembership
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.vpn import VpnAccount
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction, Wallet
from melorin.modules.orders import service as orders

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL"),
]


async def _seed(factory):
    async with factory() as session:
        world = await _world(session)
        return {
            "store": world.store.id,
            "user": world.user.id,
            "membership": world.ctx.membership.id,
            "product": world.product.id,
            "other_product": world.other.id,
            "bundle": world.bundle.id,
            "account": world.account.id,
            "wallet": world.wallet_id,
        }


async def _request(factory, ids, *, key, product, kind, renewal_mode="replace"):
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
                idempotency_key=key,
                kind=kind,
                vpn_account_id=ids["account"] if kind == "renewal" else None,
                bundle_id=ids["bundle"] if kind == "purchase" else None,
                renewal_mode=renewal_mode,
            )
            return ("ok", order.id, order.status)
        except AppError as exc:
            await session.rollback()
            return ("error", exc.code)


async def _assert_one_charge(factory, ids, kind):
    async with factory() as session:
        orders_created = (
            select(func.count())
            .select_from(Order)
            .where(Order.kind == kind, Order.idempotency_key.in_(("purchase-race", "renewal-race", "another-key")))
        )
        assert await session.scalar(orders_created) == 1
        assert (await session.get(Wallet, ids["wallet"])).balance == 48_000
        assert await session.scalar(select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.kind == "purchase")) == 1
        assert await session.scalar(select(func.sum(LedgerEntry.amount))) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.topic == "order.paid")) == 1


async def test_parallel_purchase_replays_the_same_order(monkeypatch):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        ids = await _seed(factory)
        barrier = asyncio.Barrier(2)
        next_code = codes.next_code

        async def synchronize_insert(session, sequence):
            await asyncio.wait_for(barrier.wait(), timeout=30)
            return await next_code(session, sequence)

        monkeypatch.setattr(codes, "next_code", synchronize_insert)
        calls = [_request(factory, ids, key="purchase-race", product=ids["product"], kind="purchase") for _ in range(2)]
        results = await asyncio.wait_for(asyncio.gather(*calls), timeout=45)
        assert results[0] == results[1]
        assert results[0][0] == "ok" and results[0][2] == "paid"
        await _assert_one_charge(factory, ids, "purchase")


@pytest.mark.parametrize("scenario", ["same_key", "different_key", "different_product", "different_mode"])
async def test_parallel_renewal_rechecks_the_key_after_the_account_lock(monkeypatch, scenario):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        ids = await _seed(factory)
        first_locked = asyncio.Event()
        second_waiting = asyncio.Event()
        lock = StoreScope.lock

        async def synchronized_lock(scope, session, model, row_id):
            if model is not VpnAccount:
                return await lock(scope, session, model, row_id)
            if asyncio.current_task().get_name() == "first-renewal":
                account = await lock(scope, session, model, row_id)
                first_locked.set()
                await asyncio.wait_for(second_waiting.wait(), timeout=30)
                return account
            await asyncio.wait_for(first_locked.wait(), timeout=30)
            second_waiting.set()
            return await lock(scope, session, model, row_id)

        monkeypatch.setattr(StoreScope, "lock", synchronized_lock)
        first = asyncio.create_task(
            _request(factory, ids, key="renewal-race", product=ids["product"], kind="renewal"), name="first-renewal"
        )
        second = asyncio.create_task(
            _request(
                factory,
                ids,
                key="another-key" if scenario == "different_key" else "renewal-race",
                product=ids["other_product"] if scenario == "different_product" else ids["product"],
                kind="renewal",
                renewal_mode="queue" if scenario == "different_mode" else "replace",
            ),
            name="second-renewal",
        )
        winner, follower = await asyncio.wait_for(asyncio.gather(first, second), timeout=45)
        assert winner[0] == "ok" and winner[2] == "paid"
        if scenario == "same_key":
            assert follower == winner
        elif scenario == "different_key":
            assert follower == ("error", "RENEWAL_IN_PROGRESS")
        else:
            assert follower == ("error", "IDEMPOTENCY_KEY_REUSE")
        await _assert_one_charge(factory, ids, "renewal")
