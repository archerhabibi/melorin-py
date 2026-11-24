"""Refunds restore referral debt that a later commission had offset."""

import pytest
from sqlalchemy import select

from _db import open_session
from test_referral_coupon_store_scope import _complete
from test_referral_replay import setup_plans
from melorin.kernel.models.referral import Commission, CommissionClawback
from melorin.kernel.models.wallet import Wallet
from melorin.modules.referral import service as referral


@pytest.mark.parametrize("debt", [300, 500])
async def test_refund_restores_all_or_partially_offset_clawback(debt):
    async with open_session() as session:
        referrer, referred, store, product = await setup_plans(session)
        claw = CommissionClawback(referrer_user_id=referrer.id, store_id=store.id, currency=store.currency, outstanding=debt)
        session.add(claw)
        await session.commit()
        first = await _complete(session, referred, store, product)
        await referral.on_order_completed(session, first.id)
        await session.commit()
        commission = await session.scalar(select(Commission).where(Commission.order_id == first.id))
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == referrer.id, Wallet.store_id == store.id))
        assert (commission.amount, commission.offset_amount, claw.outstanding, wallet.balance) == (500, debt, 0, 500 - debt)

        first.status = "refunded"
        await session.commit()
        for _ in range(2):
            await referral.on_order_refunded(session, first.id)
            await session.commit()
        assert commission.status == "reversed"
        assert claw.outstanding == debt
        assert wallet.balance == 0

        later = await _complete(session, referred, store, product)
        await referral.on_order_completed(session, later.id)
        await session.commit()
        later_commission = await session.scalar(select(Commission).where(Commission.order_id == later.id))
        assert later_commission.kind == "commission"
        assert later_commission.offset_amount == min(debt, 300)
        assert claw.outstanding == max(debt - 300, 0)
        assert wallet.balance == max(300 - debt, 0)
