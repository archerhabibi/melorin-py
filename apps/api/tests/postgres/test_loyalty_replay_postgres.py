"""Loyalty redemption retries must survive PostgreSQL account-lock contention."""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine, pg_url
from test_loyalty_service import _reward, _world
from melorin.core.errors import AppError
from melorin.kernel.models.identity import User
from melorin.kernel.models.loyalty import LoyaltyAccount, LoyaltyRedemption, LoyaltyReward, LoyaltyTransaction
from melorin.kernel.models.stores import Store
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction, Wallet
from melorin.modules.loyalty import redemption, service as club

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL"),
]


@pytest.mark.parametrize("scenario", ["balance", "stock", "customer_limit", "different_reward", "different_key"])
async def test_concurrent_redemption_rechecks_the_key_after_locking(monkeypatch, scenario):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            store, customer, _, admin = await _world(session)
            first_reward = await _reward(
                session,
                store,
                admin,
                cost_points=10,
                stock=1 if scenario in ("stock", "different_key") else None,
                per_user_limit=1 if scenario == "customer_limit" else None,
            )
            other_reward = await _reward(session, store, admin, name="other", cost_points=10)
            points = 10 if scenario == "balance" else 100
            await club.adjust(session, store, customer.id, points, reason="test", actor_id=admin.id, actor_type="admin")
            await session.commit()
            store_id, user_id, reward_id, other_id = store.id, customer.id, first_reward.id, other_reward.id

        first_locked, second_waiting = asyncio.Event(), asyncio.Event()
        get_account = redemption.get_account

        async def synchronized_get_account(session, store_id, user_id, *, lock=False):
            if not lock:
                return await get_account(session, store_id, user_id, lock=lock)
            if asyncio.current_task().get_name() == "first-redemption":
                account = await get_account(session, store_id, user_id, lock=True)
                first_locked.set()
                await asyncio.wait_for(second_waiting.wait(), timeout=30)
                return account
            await asyncio.wait_for(first_locked.wait(), timeout=30)
            second_waiting.set()
            return await get_account(session, store_id, user_id, lock=True)

        monkeypatch.setattr(redemption, "get_account", synchronized_get_account)

        async def request(key, selected_reward):
            async with factory() as session:
                try:
                    row, created = await club.redeem(
                        session,
                        await session.get(Store, store_id),
                        await session.get(User, user_id),
                        selected_reward,
                        idempotency_key=key,
                    )
                    result = ("ok", row.id, created)
                    await session.commit()
                    return result
                except AppError as exc:
                    await session.rollback()
                    return ("error", exc.code)

        first = asyncio.create_task(request("redeem-key", reward_id), name="first-redemption")
        second = asyncio.create_task(
            request(
                "different-key" if scenario == "different_key" else "redeem-key", other_id if scenario == "different_reward" else reward_id
            ),
            name="second-redemption",
        )
        winner, follower = await asyncio.wait_for(asyncio.gather(first, second), timeout=45)
        assert winner[0] == "ok" and winner[2] is True
        if scenario == "different_reward":
            assert follower == ("error", "IDEMPOTENCY_KEY_REUSED")
        elif scenario == "different_key":
            assert follower == ("error", "LOYALTY_REWARD_SOLD_OUT")
        else:
            assert follower == ("ok", winner[1], False)

        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(LoyaltyRedemption)) == 1
            account = await session.scalar(select(LoyaltyAccount).where(LoyaltyAccount.user_id == user_id))
            assert account.balance == points - 10
            assert (await session.get(LoyaltyReward, reward_id)).redeemed_count == 1
            assert (
                await session.scalar(select(func.count()).select_from(LoyaltyTransaction).where(LoyaltyTransaction.kind == "redeem")) == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.kind == "loyalty_reward"))
                == 1
            )
            assert await session.scalar(select(func.sum(LedgerEntry.amount))) == 0
            assert (await session.scalar(select(Wallet).where(Wallet.user_id == user_id, Wallet.store_id == store_id))).balance == 5000
