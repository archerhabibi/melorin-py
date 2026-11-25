"""PostgreSQL serialization for referral refunds and clawback offsets."""

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine, pg_url
from test_referral_coupon_store_scope import _complete
from test_referral_replay import setup_plans
from test_reward_refund_race_postgres import blocked_by_another_transaction
from melorin.kernel.models.referral import Commission, CommissionClawback
from melorin.kernel.models.wallet import Wallet
from melorin.modules.referral import commissions
from melorin.modules.wallet import service as wallet

pytestmark = [pytest.mark.concurrency, pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL")]


async def seed_refund(factory, *, spend):
    async with factory() as session:
        referrer, referred, store, product = await setup_plans(session)
        session.add(CommissionClawback(referrer_user_id=referrer.id, store_id=store.id, currency=store.currency, outstanding=300))
        await session.commit()
        first = await _complete(session, referred, store, product)
        await commissions.on_order_completed(session, first.id)
        await session.commit()
        w = await session.scalar(select(Wallet).where(Wallet.user_id == referrer.id, Wallet.store_id == store.id))
        if spend:
            await wallet.post(
                session,
                kind="test_spend",
                key=f"test-spend:{first.id}",
                currency=store.currency,
                store_id=store.id,
                postings=[wallet.Posting(-200, wallet=w), wallet.Posting(200, account=wallet.acc_revenue(store.id))],
            )
        first.status = "refunded"
        await session.commit()
        later = await _complete(session, referred, store, product)
        return first.id, later.id, referrer.id, store.id


async def test_two_refund_workers_restore_the_offset_once():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        first_id, _, referrer_id, store_id = await seed_refund(factory, spend=False)

        async def refund():
            async with factory() as session:
                await commissions.on_order_refunded(session, first_id)
                await session.commit()

        await asyncio.wait_for(asyncio.gather(refund(), refund()), timeout=30)
        async with factory() as session:
            c = await session.scalar(select(Commission).where(Commission.order_id == first_id))
            claw = await session.scalar(select(CommissionClawback).where(CommissionClawback.referrer_user_id == referrer_id))
            w = await session.scalar(select(Wallet).where(Wallet.user_id == referrer_id, Wallet.store_id == store_id))
            assert (c.status, c.reversed_amount, claw.outstanding, w.balance) == ("reversed", 200, 300, 0)


async def test_refund_and_new_commission_use_the_same_lock_order(monkeypatch):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        first_id, later_id, referrer_id, store_id = await seed_refund(factory, spend=True)
        entered, release = asyncio.Event(), asyncio.Event()
        pid = asyncio.get_running_loop().create_future()
        post = wallet.post

        async def hold_commission(session, *, kind, **kwargs):
            if kind == "referral_commission":
                entered.set()
                await asyncio.wait_for(release.wait(), timeout=30)
            return await post(session, kind=kind, **kwargs)

        monkeypatch.setattr(wallet, "post", hold_commission)

        async def settle():
            async with factory() as session:
                await commissions.on_order_completed(session, later_id)
                await session.commit()

        async def refund():
            async with factory() as session:
                pid.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
                await commissions.on_order_refunded(session, first_id)
                await session.commit()

        first = asyncio.create_task(settle())
        await asyncio.wait_for(entered.wait(), timeout=15)
        second = asyncio.create_task(refund())
        try:
            blocked = await blocked_by_another_transaction(factory, await asyncio.wait_for(pid, timeout=15), second)
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=30)
        assert blocked, "refund and settlement must serialize on shared financial state"
        async with factory() as session:
            refunded = await session.scalar(select(Commission).where(Commission.order_id == first_id))
            later = await session.scalar(select(Commission).where(Commission.order_id == later_id))
            claw = await session.scalar(select(CommissionClawback).where(CommissionClawback.referrer_user_id == referrer_id))
            w = await session.scalar(select(Wallet).where(Wallet.user_id == referrer_id, Wallet.store_id == store_id))
            assert (refunded.status, refunded.reversed_amount, claw.outstanding, w.balance) == ("reversed", 200, 300, 100)
            assert (later.kind, later.amount, later.offset_amount) == ("commission", 300, 0)
