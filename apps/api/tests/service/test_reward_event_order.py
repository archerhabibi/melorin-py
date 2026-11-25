"""Refunded orders must not receive rewards from a delayed completion event."""

import pytest
from sqlalchemy import func, select

from _db import make_user, open_session
from test_loyalty_service import _complete, _join, _world
from melorin.kernel.models.loyalty import LoyaltyTransaction
from melorin.kernel.models.referral import Commission, CommissionRule, ReferralRelationship
from melorin.modules.loyalty import service as loyalty
from melorin.modules.referral import service as referral
from melorin.worker import runner


async def seed_rewards(session):
    store, customer, product, _ = await _world(session, first_order_bonus=50, referral_bonus=200)
    referrer = await make_user(session)
    await _join(session, store, referrer)
    session.add(ReferralRelationship(store_id=store.id, referrer_user_id=referrer.id, referred_user_id=customer.id))
    session.add(CommissionRule(store_id=store.id, kind="signup_reward", model="fixed", value=500, is_active=True))
    await session.commit()
    order = await _complete(session, customer, store, product, total=10_000)
    return order, customer, referrer


@pytest.mark.parametrize("engine", ["loyalty", "referral", "worker"])
async def test_delayed_completion_after_refund_does_not_award_rewards(engine):
    async with open_session() as session:
        order, _, _ = await seed_rewards(session)
        order.status = "refunded"
        await session.commit()
        if engine == "worker":
            await runner._on_order_refunded(session, {"order_id": str(order.id)})
            await runner._on_order_completed(session, {"order_id": str(order.id)})
        else:
            service = loyalty if engine == "loyalty" else referral
            await service.on_order_refunded(session, order.id)
            await service.on_order_completed(session, order.id)
        await session.commit()
        counts = (
            await session.scalar(select(func.count()).select_from(LoyaltyTransaction)),
            await session.scalar(select(func.count()).select_from(Commission)),
        )
        assert counts == (0, 0)
