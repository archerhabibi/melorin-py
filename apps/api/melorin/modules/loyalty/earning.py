"""Loyalty club: earning (see ``service.py`` for the facade and the overview)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import events
from melorin.domain import loyalty as rules
from melorin.domain.loyalty import Program, Tier
from melorin.domain.order_kinds import is_revenue, revenue_only
from melorin.domain.order_state import OrderStatus
from melorin.kernel.models.loyalty import (
    LoyaltyAccount,
    LoyaltyTransaction,
)
from melorin.kernel.models.orders import Order
from melorin.kernel.models.referral import ReferralRelationship
from melorin.modules.loyalty.common import _REVERSIBLE
from melorin.modules.loyalty.ledger import _find_tx, _post, get_account
from melorin.modules.loyalty.program import get_program, program_rules
from melorin.modules.loyalty.tiers import ladder, load_tiers


async def _earn(
    session: AsyncSession, acc: LoyaltyAccount, points: int, *, kind: str, key: str, order_id: uuid.UUID | None, memo: str
) -> LoyaltyTransaction | None:
    """Credit earned points: an older points debt is settled first, the tier counts everything that was earned."""
    if points <= 0:
        return None
    credited, recovered = rules.offset_with_debt(points, acc.debt)
    tx, created = await _post(session, acc, kind=kind, amount=credited, key=key, order_id=order_id, memo=memo, debt_recovered=recovered)
    if created:
        acc.debt -= recovered
        acc.lifetime_earned += points
    return tx


async def _is_first_order(session: AsyncSession, order: Order) -> bool:
    prior = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.user_id == order.user_id,
            Order.store_id == order.store_id,
            Order.status == OrderStatus.COMPLETED,
            revenue_only(Order.kind),
            Order.total > 0,
            Order.completed_at < order.completed_at,
        )
    )
    return not prior


async def on_order_completed(session: AsyncSession, order_id: uuid.UUID) -> None:
    """Points for a completed order of THIS store's own club: the order points, the first-order bonus and the referrer's bonus."""
    # Refunds lock this same row before changing the status. Re-read it under
    # the lock so a delayed completion cannot award rewards after a refund.
    order = await session.get(Order, order_id, with_for_update=True, populate_existing=True)
    if not order or order.status != OrderStatus.COMPLETED or not is_revenue(order.kind) or order.total <= 0:
        return
    row = await get_program(session, order.store_id)
    if not row or not row.is_enabled:
        return
    program = program_rules(row)
    tiers = ladder(await load_tiers(session, order.store_id))
    acc = await get_account(session, order.store_id, order.user_id, lock=True)
    tier_before = rules.tier_for(tiers, acc.lifetime_earned)
    earned = 0
    tx = await _earn(
        session,
        acc,
        rules.order_points(order.total, program, rules.multiplier_for(tiers, acc.lifetime_earned)),
        kind="order_earn",
        key=f"loyalty:earn:{order.id}",
        order_id=order.id,
        memo=f"امتیاز سفارش {order.number}",
    )
    earned += (tx.amount + tx.debt_recovered) if tx else 0
    first = program.first_order_bonus > 0 or program.referral_bonus > 0
    if first and order.completed_at and await _is_first_order(session, order):
        bonus = await _earn(
            session,
            acc,
            program.first_order_bonus,
            kind="first_order_bonus",
            key=f"loyalty:first:{order.store_id}:{order.user_id}",
            order_id=order.id,
            memo="پاداش اولین خرید",
        )
        earned += (bonus.amount + bonus.debt_recovered) if bonus else 0
        await _referrer_bonus(session, order, program)
    tier_after = rules.tier_for(tiers, acc.lifetime_earned)
    if earned > 0:
        await _notify_earned(session, order, earned, tier_before, tier_after)


async def _referrer_bonus(session: AsyncSession, order: Order, program: Program) -> None:
    """The person who invited this customer into THIS store gets points once, when the friend completes the first order."""
    if program.referral_bonus <= 0:
        return
    rel = await session.scalar(
        select(ReferralRelationship).where(
            ReferralRelationship.store_id == order.store_id, ReferralRelationship.referred_user_id == order.user_id
        )
    )
    if not rel:
        return
    racc = await get_account(session, order.store_id, rel.referrer_user_id, lock=True)
    await _earn(
        session,
        racc,
        program.referral_bonus,
        kind="referral_bonus",
        key=f"loyalty:referral:{order.store_id}:{order.user_id}",
        order_id=order.id,
        memo="پاداش معرفی دوست",
    )
    await events.emit_user_notice(
        session,
        rel.referrer_user_id,
        order.store_id,
        "loyalty",
        "امتیاز معرفی",
        f"{program.referral_bonus:,} امتیاز بابت اولین خرید دوست شما به باشگاه مشتریان اضافه شد.",
        dedup_key=f"notify:loyalty:referral:{order.store_id}:{order.user_id}",
    )


async def _notify_earned(session: AsyncSession, order: Order, earned: int, before: Tier | None, after: Tier | None) -> None:
    body = f"{earned:,} امتیاز بابت سفارش {order.number} به باشگاه مشتریان شما اضافه شد."
    if after and (before is None or after.name != before.name):
        body += f"\nتبریک! به سطح «{after.name}» رسیدید."
    await events.emit_user_notice(
        session, order.user_id, order.store_id, "loyalty", "باشگاه مشتریان", body, dedup_key=f"notify:loyalty:{order.id}"
    )


async def on_order_refunded(session: AsyncSession, order_id: uuid.UUID) -> None:
    """Take back every point this order created (its own points, the first-order bonus, the referrer's bonus).

    What the balance still covers is removed now; what the customer already spent becomes a points debt recovered from his next
    earnings. The tier follows, because the lifetime total shrinks by the whole reversed amount.
    """
    originals = (
        await session.scalars(
            select(LoyaltyTransaction).where(LoyaltyTransaction.order_id == order_id, LoyaltyTransaction.kind.in_(_REVERSIBLE))
        )
    ).all()
    for tx in originals:
        if await _find_tx(session, f"loyalty:reversal:{tx.id}"):
            continue
        acc = await session.scalar(
            select(LoyaltyAccount).where(LoyaltyAccount.id == tx.account_id).with_for_update().execution_options(populate_existing=True)
        )
        if not acc:
            continue
        earned = tx.amount + tx.debt_recovered
        take, owed = rules.split_reversal(earned, acc.balance)
        _, created = await _post(
            session,
            acc,
            kind="reversal",
            amount=-take,
            key=f"loyalty:reversal:{tx.id}",
            order_id=order_id,
            reverses_id=tx.id,
            memo="برگشت امتیاز به‌دلیل استرداد سفارش",
        )
        if created:
            acc.debt += owed
            acc.lifetime_earned = max(0, acc.lifetime_earned - earned)
            await events.emit_user_notice(
                session,
                acc.user_id,
                acc.store_id,
                "loyalty",
                "باشگاه مشتریان",
                f"{earned:,} امتیاز به‌دلیل استرداد سفارش از باشگاه مشتریان کسر شد.",
                dedup_key=f"notify:loyalty:reversal:{tx.id}",
            )
