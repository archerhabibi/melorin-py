"""Real PostgreSQL ordering for a refund racing reward settlement."""

import asyncio

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine, pg_url
from test_reward_event_order import seed_rewards
from melorin.kernel.models.loyalty import LoyaltyAccount, LoyaltyTransaction
from melorin.kernel.models.orders import Order
from melorin.kernel.models.referral import Commission
from melorin.kernel.models.wallet import Wallet
from melorin.modules.orders import service as orders
from melorin.modules.referral import commissions
from melorin.worker import runner

pytestmark = [pytest.mark.concurrency, pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL")]


async def blocked_by_another_transaction(factory, pid, task):
    async with factory() as observer:
        for _ in range(120):
            blocked = await observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid})
            if blocked:
                return True
            if task.done():
                return False
            await asyncio.sleep(0.05)
    return False


@pytest.mark.parametrize("scenario", ["refund_first", "settlement_first"])
async def test_refund_and_reward_settlement_serialize_on_the_order(monkeypatch, scenario):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            order, customer, referrer = await seed_rewards(session)
            order_id, customer_id, referrer_id, store_id = order.id, customer.id, referrer.id, order.store_id
        payload = {"order_id": str(order_id)}
        release = asyncio.Event()
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()
        pid = loop.create_future()

        async def settle(capture_pid=False):
            async with factory() as session:
                if capture_pid:
                    pid.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
                await runner._on_order_completed(session, payload)
                await session.commit()

        async def refund(capture_pid=False):
            async with factory() as session:
                if capture_pid:
                    pid.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
                await orders.auto_refund(session, order_id, reason="test")

        async def reverse():
            async with factory() as session:
                await runner._on_order_refunded(session, payload)
                await session.commit()

        if scenario == "refund_first":

            async def hold_refund():
                async with factory() as session:
                    row = await session.get(Order, order_id, with_for_update=True)
                    entered.set()
                    await asyncio.wait_for(release.wait(), timeout=30)
                    row.status = "refunded"
                    await session.commit()

            first = asyncio.create_task(hold_refund())
            await asyncio.wait_for(entered.wait(), timeout=15)
            second = asyncio.create_task(settle(capture_pid=True))
        else:
            plan = commissions._plan

            async def hold_settlement(session, order, kind):
                entered.set()
                await asyncio.wait_for(release.wait(), timeout=30)
                return await plan(session, order, kind)

            monkeypatch.setattr(commissions, "_plan", hold_settlement)
            first = asyncio.create_task(settle())
            await asyncio.wait_for(entered.wait(), timeout=15)
            second = asyncio.create_task(refund(capture_pid=True))

        try:
            blocked = await blocked_by_another_transaction(factory, await asyncio.wait_for(pid, timeout=15), second)
            if scenario == "settlement_first" and not blocked:
                await asyncio.wait_for(second, timeout=15)
                await reverse()  # the refund event saw no rewards on the parent
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=30)
        if scenario == "settlement_first" and blocked:
            await reverse()
        assert blocked, "refund and reward settlement must serialize on the order row"

        async with factory() as session:
            assert (await session.get(Order, order_id)).status == "refunded"
            accounts = (await session.scalars(select(LoyaltyAccount).where(LoyaltyAccount.user_id.in_([customer_id, referrer_id])))).all()
            assert all((a.balance, a.debt, a.lifetime_earned) == (0, 0, 0) for a in accounts)
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == referrer_id, Wallet.store_id == store_id))
            assert wallet is None or wallet.balance == 0
            rows = (await session.scalars(select(Commission).where(Commission.order_id == order_id))).all()
            if scenario == "refund_first":
                assert rows == []
                assert await session.scalar(select(func.count()).select_from(LoyaltyTransaction)) == 0
            else:
                assert len(rows) == 1 and rows[0].status == "reversed"
