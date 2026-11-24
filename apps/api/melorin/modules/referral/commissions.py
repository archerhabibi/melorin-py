"""referral: commissions (see ``service.py`` for the facade)."""

import uuid

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events, settings_store
from melorin.domain.commission import Plan, amount_for, offset_with_outstanding, split_reversal
from melorin.domain.order_kinds import is_revenue, revenue_only
from melorin.domain.order_state import OrderStatus
from melorin.kernel.models.orders import Order
from melorin.kernel.models.referral import Commission, CommissionClawback, CommissionRule, ReferralRelationship
from melorin.kernel.models.stores import Store
from melorin.modules.eventcenter import topics as ec_topics
from melorin.modules.wallet import service as wallet


async def _plan(session: AsyncSession, order: Order, kind: str) -> Plan | None:
    rows = (
        await session.scalars(
            select(CommissionRule).where(
                CommissionRule.store_id == order.store_id, CommissionRule.kind == kind, CommissionRule.is_active.is_(True)
            )
        )
    ).all()
    specific = next((r for r in rows if r.product_id == order.product_id), None)
    rule = specific or next((r for r in rows if r.product_id is None), None)
    if rule:
        return Plan(kind=rule.kind, model=rule.model, value=rule.value, max_amount=rule.max_amount, active=rule.is_active)
    store = await session.get(Store, order.store_id)
    if not store or store.kind != "main":
        return None  # a reseller store pays only what ITS owner configured; the main store's defaults never leak into it
    # Backward-compatible global settings: the MAIN store's default when Admin has not defined a rule for it.
    if kind == "signup_reward":
        return Plan(kind, "fixed", int(await settings_store.get(session, "referral.signup_reward") or 0))
    return Plan(kind, "percent", int(await settings_store.get(session, "referral.commission_bp") or 0))


async def on_order_completed(session: AsyncSession, order_id: uuid.UUID) -> None:
    # Refunds lock this same row before changing the status. Re-read it under
    # the lock so a delayed completion cannot award rewards after a refund.
    order = await session.get(Order, order_id, with_for_update=True, populate_existing=True)
    if not order or order.status != OrderStatus.COMPLETED or not is_revenue(order.kind) or order.total <= 0:
        return
    # The order lock also serializes retries. A replay must not turn the first
    # purchase's signup reward into a second, ordinary commission.
    if await session.scalar(select(Commission.id).where(Commission.order_id == order.id)):
        return
    # Store isolation (docs/17): the relationship is looked up INSIDE the order's own store. A referral made in another store
    # never pays here and never charges this store's referral-expense account; this store's own relationship (if any) is the one used.
    rel = await session.scalar(
        select(ReferralRelationship).where(
            ReferralRelationship.referred_user_id == order.user_id, ReferralRelationship.store_id == order.store_id
        )
    )
    if not rel:
        return
    prior = (
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.user_id == order.user_id,
                # "First purchase" is counted inside the referral's own store: a purchase made earlier in another store must not
                # downgrade the signup reward of this store to a plain commission.
                Order.store_id == order.store_id,
                Order.status == OrderStatus.COMPLETED,
                revenue_only(Order.kind),
                Order.total > 0,
                Order.completed_at < order.completed_at,
            )
        )
        or 0
    )
    # The reward is one per customer per store (unique key). If it was already granted - even when that first order was later
    # refunded and so no longer counts as "completed" - every further order pays the commission plan, never a second reward.
    reward_granted = await session.scalar(
        select(Commission.id).where(
            Commission.store_id == order.store_id, Commission.referred_user_id == order.user_id, Commission.kind == "signup_reward"
        )
    )
    kind = "signup_reward" if prior == 0 and not reward_granted else "commission"
    plan = await _plan(session, order, kind)
    gross = amount_for(plan, order.total)
    if gross <= 0:
        return
    w = await wallet.get_wallet(session, rel.referrer_user_id, order.store_id, currency=order.currency)
    claw = await session.scalar(
        select(CommissionClawback)
        .where(
            CommissionClawback.referrer_user_id == rel.referrer_user_id,
            CommissionClawback.store_id == order.store_id,
            CommissionClawback.currency == order.currency,
        )
        .with_for_update()
    )
    outstanding = claw.outstanding if claw else 0
    payout, recovered = offset_with_outstanding(gross, outstanding)
    if recovered and claw:
        claw.outstanding -= recovered
    tx = None
    if payout:
        tx, _ = await wallet.post(
            session,
            kind="referral_" + kind,
            key=f"referral:{order.id}:{kind}",
            currency=order.currency,
            store_id=order.store_id,
            order_id=order.id,
            postings=[wallet.Posting(payout, wallet=w), wallet.Posting(-payout, account=wallet.acc_referral_expense(order.store_id))],
            memo="پاداش معرفی" if kind == "signup_reward" else "کمیسیون معرفی",
        )
    session.add(
        Commission(
            store_id=order.store_id,
            order_id=order.id,
            referrer_user_id=rel.referrer_user_id,
            referred_user_id=order.user_id,
            kind=kind,
            amount=gross,
            offset_amount=recovered,
            status="credited",
            ledger_tx_id=tx.id if tx else None,
            currency=order.currency,
        )
    )
    if recovered:
        audit.record(
            session,
            "commission.clawback_offset",
            actor_type="system",
            entity_type="commission",
            entity_id=order.id,
            store_id=order.store_id,
            data={"recovered": recovered, "gross": gross},
        )
    await events.emit_user_notice(
        session,
        rel.referrer_user_id,
        order.store_id,
        "referral",
        "پاداش معرفی",
        f"مبلغ {payout:,} به کیف پول شما اضافه شد.",
        dedup_key=f"notify:referral:{order.id}:{kind}",
    )
    head = "🎁 پاداش اولین خرید معرف" if kind == "signup_reward" else "🤝 کمیسیون معرف"
    text = f"{head}\nسفارش: {order.number}\nمبلغ: {gross:,} {order.currency}"
    if recovered:
        text += f"\nکسر بدهی قبلی معرف: {recovered:,}"
    await events.emit(
        session,
        events.EVENT_CENTER,
        {"store_id": order.store_id, "topic": ec_topics.AFFILIATE, "text": text},
        dedup_key=f"ec:affiliate:{order.id}:{kind}",
    )


async def on_order_refunded(session: AsyncSession, order_id: uuid.UUID) -> None:
    rows = (
        await session.scalars(select(Commission).where(Commission.order_id == order_id, Commission.status == "credited").with_for_update())
    ).all()
    for c in rows:
        if c.ledger_tx_id:
            w = await wallet.get_wallet(session, c.referrer_user_id, c.store_id, currency=c.currency or "IRT")
            await wallet.lock_wallets(session, [w])
            take, outstanding = split_reversal(c.amount - c.offset_amount, w.balance)
            if take:
                await wallet.post(
                    session,
                    kind="commission_reversal",
                    key=f"commission_reversal:{c.id}",
                    currency=w.currency,
                    store_id=c.store_id,
                    order_id=order_id,
                    postings=[
                        wallet.Posting(-take, wallet=w, min_balance=0),
                        wallet.Posting(take, account=wallet.acc_referral_expense(c.store_id)),
                    ],
                    memo="برگشت کمیسیون به‌دلیل استرداد",
                )
            if outstanding:
                claw = await session.scalar(
                    select(CommissionClawback)
                    .where(
                        CommissionClawback.referrer_user_id == c.referrer_user_id,
                        CommissionClawback.store_id == c.store_id,
                        CommissionClawback.currency == w.currency,
                    )
                    .with_for_update()
                )
                if not claw:
                    claw = CommissionClawback(referrer_user_id=c.referrer_user_id, store_id=c.store_id, currency=w.currency, outstanding=0)
                    session.add(claw)
                claw.outstanding += outstanding
            c.reversed_amount = take + outstanding
            c.status = "reversed"
            order = await session.get(Order, order_id)
            text = f"↩️ کمیسیون معرف به‌دلیل استرداد برگشت خورد\nسفارش: {order.number if order else '-'}\nبرگشت‌شده: {take:,} {c.currency or ''}".rstrip()
            if outstanding:
                text += f"\nبدهی باقی‌مانده معرف: {outstanding:,}"
            await events.emit(
                session,
                events.EVENT_CENTER,
                {"store_id": c.store_id, "topic": ec_topics.AFFILIATE, "text": text},
                dedup_key=f"ec:affiliate:reversal:{c.id}",
            )


async def earnings(session: AsyncSession, referrer_id: uuid.UUID, store_id: uuid.UUID) -> dict:
    """What ``referrer_id`` really earned in ONE store: summed in the database over ALL his commissions there.

    The customer screens list only the latest commissions, so adding up that list under-reports an active referrer; this is
    the single source of the number. A reversed commission keeps only what was not taken back (normally nothing)."""
    net = Commission.amount - Commission.offset_amount - case((Commission.status == "reversed", Commission.reversed_amount), else_=0)
    total, count = (
        await session.execute(
            select(func.coalesce(func.sum(net), 0), func.count()).where(
                Commission.referrer_user_id == referrer_id, Commission.store_id == store_id
            )
        )
    ).one()
    return {"earned": max(0, int(total)), "commissions_total": int(count)}


async def store_summary(session: AsyncSession, store_id: uuid.UUID, *, top: int = 5) -> dict:
    """Numbers of ONE store's programme: members invited, what was paid, reversed and is still owed back."""
    invited = (
        await session.scalar(select(func.count()).select_from(ReferralRelationship).where(ReferralRelationship.store_id == store_id)) or 0
    )
    referrers = (
        await session.scalar(
            select(func.count(func.distinct(ReferralRelationship.referrer_user_id))).where(ReferralRelationship.store_id == store_id)
        )
        or 0
    )
    paid_rows = (
        await session.execute(
            select(
                Commission.kind,
                Commission.status,
                func.count(),
                func.coalesce(func.sum(Commission.amount), 0),
                func.coalesce(func.sum(Commission.offset_amount), 0),
                func.coalesce(func.sum(Commission.reversed_amount), 0),
            )
            .where(Commission.store_id == store_id)
            .group_by(Commission.kind, Commission.status)
        )
    ).all()
    kinds: dict[str, dict] = {}
    total_paid = total_reversed = 0
    for kind, status, n, amount, offset, reversed_ in paid_rows:
        k = kinds.setdefault(kind, {"count": 0, "gross": 0, "reversed": 0})
        k["count"] += n
        k["gross"] += int(amount)
        k["reversed"] += int(reversed_) if status == "reversed" else 0
        total_paid += int(amount) - int(offset)
        total_reversed += int(reversed_) if status == "reversed" else 0
    outstanding = await session.scalar(
        select(func.coalesce(func.sum(CommissionClawback.outstanding), 0)).where(CommissionClawback.store_id == store_id)
    )
    leaders = (
        await session.execute(
            select(Commission.referrer_user_id, func.count(), func.coalesce(func.sum(Commission.amount - Commission.offset_amount), 0))
            .where(Commission.store_id == store_id, Commission.status == "credited")
            .group_by(Commission.referrer_user_id)
            .order_by(func.sum(Commission.amount - Commission.offset_amount).desc())
            .limit(top)
        )
    ).all()
    return {
        "store_id": store_id,
        "invited": invited,
        "referrers": referrers,
        "paid_out": total_paid,
        "reversed": total_reversed,
        "outstanding_clawback": int(outstanding or 0),
        "by_kind": kinds,
        "top_referrers": [{"user_id": uid, "rewards": int(n), "paid": int(paid)} for uid, n, paid in leaders],
    }
