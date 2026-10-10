"""Referral attribution and configurable commission plans.

Attribution is first-touch: once a relationship exists it is never replaced. Rules are
Admin-managed per Store/Product. Refunds always create a reversal; if the referrer spent
the reward, the uncovered amount becomes a clawback offset against future commissions.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events, settings_store
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain.commission import Plan, amount_for, offset_with_outstanding, split_reversal
from melorin.domain.order_state import OrderStatus
from melorin.modules.identity.models import User
from melorin.modules.orders.models import Order
from melorin.modules.referral.models import Commission, CommissionClawback, CommissionRule, ReferralRelationship
from melorin.modules.stores.models import Store
from melorin.modules.wallet import service as wallet


async def attach(session: AsyncSession, store_id: uuid.UUID, referred: User, referrer: User | None) -> None:
    """First registered referrer wins platform-wide. Later referral links are ignored."""
    if not referrer or referrer.id == referred.id:
        return
    store = await session.get(Store, store_id)
    if not store or store.kind != "main":
        return
    exists = await session.scalar(select(ReferralRelationship).where(ReferralRelationship.referred_user_id == referred.id))
    if exists:
        return
    session.add(ReferralRelationship(store_id=store_id, referrer_user_id=referrer.id, referred_user_id=referred.id))


async def _plan(session: AsyncSession, order: Order, kind: str) -> Plan | None:
    rows = (await session.scalars(select(CommissionRule).where(CommissionRule.store_id == order.store_id, CommissionRule.kind == kind, CommissionRule.is_active.is_(True)))).all()
    specific = next((r for r in rows if r.product_id == order.product_id), None)
    rule = specific or next((r for r in rows if r.product_id is None), None)
    if rule:
        return Plan(kind=rule.kind, model=rule.model, value=rule.value, max_amount=rule.max_amount, active=rule.is_active)
    # Backward-compatible settings only when no Admin rule exists.
    if kind == "signup_reward":
        return Plan(kind, "fixed", int(await settings_store.get(session, "referral.signup_reward") or 0))
    return Plan(kind, "percent", int(await settings_store.get(session, "referral.commission_bp") or 0))


async def on_order_completed(session: AsyncSession, order_id: uuid.UUID) -> None:
    order = await session.get(Order, order_id)
    if not order or order.kind == "test" or order.total <= 0:
        return
    # Relationship is platform-wide first-touch, while the commission posts in the order's Store currency.
    rel = await session.scalar(select(ReferralRelationship).where(ReferralRelationship.referred_user_id == order.user_id))
    if not rel:
        return
    prior = await session.scalar(select(func.count()).select_from(Order).where(Order.user_id == order.user_id, Order.status == OrderStatus.COMPLETED, Order.kind != "test", Order.total > 0, Order.completed_at < order.completed_at)) or 0
    kind = "signup_reward" if prior == 0 else "commission"
    plan = await _plan(session, order, kind)
    gross = amount_for(plan, order.total)
    if gross <= 0 or await session.scalar(select(Commission.id).where(Commission.order_id == order.id, Commission.kind == kind)):
        return
    w = await wallet.get_wallet(session, rel.referrer_user_id, order.store_id, currency=order.currency)
    claw = await session.scalar(select(CommissionClawback).where(CommissionClawback.referrer_user_id == rel.referrer_user_id, CommissionClawback.store_id == order.store_id, CommissionClawback.currency == order.currency).with_for_update())
    outstanding = claw.outstanding if claw else 0
    payout, recovered = offset_with_outstanding(gross, outstanding)
    if recovered and claw:
        claw.outstanding -= recovered
    tx = None
    if payout:
        tx, _ = await wallet.post(session, kind="referral_" + kind, key=f"referral:{order.id}:{kind}", currency=order.currency, store_id=order.store_id, order_id=order.id, postings=[wallet.Posting(payout, wallet=w), wallet.Posting(-payout, account=wallet.acc_referral_expense(order.store_id))], memo="پاداش معرفی" if kind == "signup_reward" else "کمیسیون معرفی")
    session.add(Commission(store_id=order.store_id, order_id=order.id, referrer_user_id=rel.referrer_user_id, kind=kind, amount=gross, offset_amount=recovered, status="credited", ledger_tx_id=tx.id if tx else None, currency=order.currency))
    if recovered:
        audit.record(session, "commission.clawback_offset", actor_type="system", entity_type="commission", entity_id=order.id, store_id=order.store_id, data={"recovered": recovered, "gross": gross})
    await events.emit(session, events.NOTIFY, {"user_id": rel.referrer_user_id, "store_id": order.store_id, "kind": "referral", "title": "پاداش معرفی", "body": f"مبلغ {payout:,} به کیف پول شما اضافه شد."}, dedup_key=f"notify:referral:{order.id}:{kind}")


async def on_order_refunded(session: AsyncSession, order_id: uuid.UUID) -> None:
    rows = (await session.scalars(select(Commission).where(Commission.order_id == order_id, Commission.status == "credited").with_for_update())).all()
    for c in rows:
        if c.ledger_tx_id:
            w = await wallet.get_wallet(session, c.referrer_user_id, c.store_id, currency=c.currency or "IRT")
            await wallet.lock_wallets(session, [w])
            take, outstanding = split_reversal(c.amount - c.offset_amount, w.balance)
            if take:
                await wallet.post(session, kind="commission_reversal", key=f"commission_reversal:{c.id}", currency=w.currency, store_id=c.store_id, order_id=order_id, postings=[wallet.Posting(-take, wallet=w, min_balance=0), wallet.Posting(take, account=wallet.acc_referral_expense(c.store_id))], memo="برگشت کمیسیون به‌دلیل استرداد")
            if outstanding:
                claw = await session.scalar(select(CommissionClawback).where(CommissionClawback.referrer_user_id == c.referrer_user_id, CommissionClawback.store_id == c.store_id, CommissionClawback.currency == w.currency).with_for_update())
                if not claw:
                    claw = CommissionClawback(referrer_user_id=c.referrer_user_id, store_id=c.store_id, currency=w.currency, outstanding=0)
                    session.add(claw)
                claw.outstanding += outstanding
            c.reversed_amount = take + outstanding
            c.status = "reversed"
