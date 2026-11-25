"""A referral order pays exactly one reward even when completion is redelivered."""

import datetime as dt

from sqlalchemy import select

from _db import open_session
from test_referral_coupon_store_scope import _complete, _world
from melorin.core.db import utcnow
from melorin.kernel.models.referral import Commission, CommissionRule
from melorin.kernel.models.wallet import Wallet
from melorin.modules.referral import service as referral


async def setup_plans(session):
    referrer, referred, store, _, product = await _world(session)
    session.add(CommissionRule(store_id=store.id, kind="commission", model="fixed", value=300, is_active=True))
    await session.commit()
    return referrer, referred, store, product


async def test_replayed_first_purchase_does_not_also_pay_a_commission():
    async with open_session() as session:
        referrer, referred, store, product = await setup_plans(session)
        order = await _complete(session, referred, store, product)
        for _ in range(3):
            await referral.on_order_completed(session, order.id)
            await session.commit()
        rows = (await session.scalars(select(Commission).where(Commission.order_id == order.id))).all()
        assert [(row.kind, row.amount) for row in rows] == [("signup_reward", 500)]
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == referrer.id, Wallet.store_id == store.id))
        assert wallet.balance == 500


async def test_later_purchase_still_pays_one_commission_on_replay():
    async with open_session() as session:
        referrer, referred, store, product = await setup_plans(session)
        first = await _complete(session, referred, store, product)
        first.completed_at = utcnow() - dt.timedelta(days=1)
        await session.commit()
        second = await _complete(session, referred, store, product)
        for order in (first, second, second):
            await referral.on_order_completed(session, order.id)
            await session.commit()
        rows = (await session.scalars(select(Commission))).all()
        assert {(row.order_id, row.kind, row.amount) for row in rows} == {
            (first.id, "signup_reward", 500),
            (second.id, "commission", 300),
        }
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == referrer.id, Wallet.store_id == store.id))
        assert wallet.balance == 800
