"""Concurrent adjustments must not acknowledge a changed amount under the same key."""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine, pg_url
from test_loyalty_service import _world
from melorin.core.errors import AppError
from melorin.kernel.models.loyalty import LoyaltyAccount, LoyaltyTransaction
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import AuditEvent
from melorin.modules.loyalty import adjustments, service as club

pytestmark = [pytest.mark.concurrency, pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL")]


@pytest.mark.parametrize("scenario", ["same", "different_amount", "opposite_sign", "different_key"])
async def test_concurrent_adjustments_verify_the_existing_amount(monkeypatch, scenario):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            store, customer, _, admin = await _world(session)
            await club.get_account(session, store.id, customer.id, lock=True)
            await session.commit()
            store_id, user_id, actor_id = store.id, customer.id, admin.id

        first_locked, second_waiting = asyncio.Event(), asyncio.Event()
        get_account = adjustments.get_account

        async def synchronized_get_account(session, store_id, user_id, *, lock=False):
            if asyncio.current_task().get_name() == "first-adjustment":
                account = await get_account(session, store_id, user_id, lock=lock)
                first_locked.set()
                await asyncio.wait_for(second_waiting.wait(), timeout=30)
                return account
            await asyncio.wait_for(first_locked.wait(), timeout=30)
            second_waiting.set()
            return await get_account(session, store_id, user_id, lock=lock)

        monkeypatch.setattr(adjustments, "get_account", synchronized_get_account)

        async def request(key, delta):
            async with factory() as session:
                try:
                    row = await club.adjust(
                        session,
                        await session.get(Store, store_id),
                        user_id,
                        delta,
                        reason="test",
                        actor_id=actor_id,
                        actor_type="admin",
                        idempotency_key=key,
                    )
                    result = ("ok", row.id, row.amount)
                    await session.commit()
                    return result
                except AppError as exc:
                    await session.rollback()
                    return ("error", exc.code)

        first = asyncio.create_task(request("adjust-key", 80), name="first-adjustment")
        delta = 120 if scenario == "different_amount" else -10 if scenario in ("opposite_sign", "different_key") else 80
        second = asyncio.create_task(request("other-key" if scenario == "different_key" else "adjust-key", delta), name="second-adjustment")
        winner, follower = await asyncio.wait_for(asyncio.gather(first, second), timeout=45)
        assert winner[0] == "ok" and winner[2] == 80
        if scenario == "same":
            assert follower == winner
        elif scenario == "different_key":
            assert follower[0] == "ok" and follower[2] == -10
        else:
            assert follower == ("error", "IDEMPOTENCY_KEY_REUSED")

        async with factory() as session:
            acc = await session.scalar(select(LoyaltyAccount).where(LoyaltyAccount.store_id == store_id, LoyaltyAccount.user_id == user_id))
            assert (acc.balance, acc.lifetime_earned) == (70 if scenario == "different_key" else 80, 80)
            expected = 2 if scenario == "different_key" else 1
            assert await session.scalar(select(func.count()).select_from(LoyaltyTransaction)) == expected
            assert (
                await session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "loyalty.points.adjusted"))
                == expected
            )
