"""Two completion workers must not pay two referral rewards for one order."""

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine, pg_url
from test_referral_coupon_store_scope import _complete
from test_referral_replay import setup_plans
from test_reward_refund_race_postgres import blocked_by_another_transaction
from melorin.kernel.models.referral import Commission
from melorin.kernel.models.wallet import Wallet
from melorin.modules.referral import commissions

pytestmark = [pytest.mark.concurrency, pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL")]


async def test_concurrent_first_purchase_completions_pay_only_once(monkeypatch):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            referrer, referred, store, product = await setup_plans(session)
            order = await _complete(session, referred, store, product)
            order_id, referrer_id, store_id = order.id, referrer.id, store.id
        entered, release = asyncio.Event(), asyncio.Event()
        pid = asyncio.get_running_loop().create_future()
        plan = commissions._plan

        async def hold_first_plan(session, order, kind):
            if not entered.is_set():
                entered.set()
                await asyncio.wait_for(release.wait(), timeout=30)
            return await plan(session, order, kind)

        monkeypatch.setattr(commissions, "_plan", hold_first_plan)

        async def settle(capture_pid=False):
            async with factory() as session:
                if capture_pid:
                    pid.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
                await commissions.on_order_completed(session, order_id)
                await session.commit()

        first = asyncio.create_task(settle())
        await asyncio.wait_for(entered.wait(), timeout=15)
        second = asyncio.create_task(settle(capture_pid=True))
        try:
            blocked = await blocked_by_another_transaction(factory, await asyncio.wait_for(pid, timeout=15), second)
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=30)
        assert blocked, "the two completion workers must serialize on the order"

        async with factory() as session:
            rows = (await session.scalars(select(Commission).where(Commission.order_id == order_id))).all()
            assert [(row.kind, row.amount) for row in rows] == [("signup_reward", 500)]
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == referrer_id, Wallet.store_id == store_id))
            assert wallet.balance == 500
