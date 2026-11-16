"""Loyalty club: summary (see ``service.py`` for the facade and the overview)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.domain import loyalty as rules
from melorin.domain.loyalty import EARN_KINDS, LoyaltyError, Reward
from melorin.kernel.models.loyalty import (
    LoyaltyAccount,
    LoyaltyRedemption,
    LoyaltyReward,
    LoyaltyTransaction,
)
from melorin.kernel.models.stores import Store
from melorin.modules.loyalty.ledger import get_account, history, tx_out
from melorin.modules.loyalty.program import get_program, program_out
from melorin.modules.loyalty.rewards import list_rewards, reward_out
from melorin.modules.loyalty.tiers import ladder, load_tiers, tier_out


async def customer_summary(session: AsyncSession, store: Store, user_id: uuid.UUID) -> dict:
    """What the club screen of ONE store shows: standing, the ladder, the rewards he can take and his latest entries."""
    row = await get_program(session, store.id)
    if not row or not row.is_enabled:
        return {"store_id": store.id, "enabled": False}
    tiers_rows = await load_tiers(session, store.id)
    tiers = ladder(tiers_rows)
    acc = await get_account(session, store.id, user_id)
    current = rules.tier_for(tiers, acc.lifetime_earned)
    upcoming, missing = rules.next_tier(tiers, acc.lifetime_earned)
    rewards = await list_rewards(session, store.id, only_active=True)
    recent, more = await history(session, store.id, user_id, limit=10)
    used: dict[uuid.UUID, int] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(LoyaltyRedemption.reward_id, func.count())
                .where(LoyaltyRedemption.store_id == store.id, LoyaltyRedemption.user_id == user_id)
                .group_by(LoyaltyRedemption.reward_id)
            )
        ).all()
    }

    def card(r: LoyaltyReward) -> dict:
        try:
            rules.check_redeem(
                Reward(r.kind, r.value, r.cost_points, r.stock, r.redeemed_count, r.per_user_limit, r.is_active),
                acc.balance,
                int(used.get(r.id, 0)),
            )
            blocked = None
        except LoyaltyError as e:
            blocked = e.code
        return reward_out(r) | {"affordable": acc.balance >= r.cost_points, "available": blocked is None, "blocked_reason": blocked}

    return {
        "store_id": store.id,
        "enabled": True,
        "currency": store.currency,
        "balance": acc.balance,
        "lifetime_earned": acc.lifetime_earned,
        "debt": acc.debt,
        "tier": None if not current else {"name": current.name, "min_points": current.min_points, "multiplier_bp": current.multiplier_bp},
        "next_tier": None if not upcoming else {"name": upcoming.name, "min_points": upcoming.min_points, "points_missing": missing},
        "tiers": [tier_out(t) for t in tiers_rows],
        "program": program_out(row),
        "rewards": [card(r) for r in rewards],
        "history": [tx_out(t) for t in recent],
        "history_more": more,
    }


async def store_summary(session: AsyncSession, store_id: uuid.UUID, *, top: int = 5) -> dict:
    """Numbers of ONE store's club: members, points outstanding, what was issued and redeemed, and the tier distribution."""
    members = await session.scalar(select(func.count()).select_from(LoyaltyAccount).where(LoyaltyAccount.store_id == store_id)) or 0
    outstanding, debt = (
        await session.execute(
            select(func.coalesce(func.sum(LoyaltyAccount.balance), 0), func.coalesce(func.sum(LoyaltyAccount.debt), 0)).where(
                LoyaltyAccount.store_id == store_id
            )
        )
    ).one()
    issued = await session.scalar(
        select(func.coalesce(func.sum(LoyaltyTransaction.amount + LoyaltyTransaction.debt_recovered), 0)).where(
            LoyaltyTransaction.store_id == store_id, LoyaltyTransaction.kind.in_(EARN_KINDS)
        )
    )
    redeemed_points, redeemed_count, paid_value = (
        await session.execute(
            select(
                func.coalesce(func.sum(LoyaltyRedemption.points_spent), 0),
                func.count(),
                func.coalesce(func.sum(LoyaltyRedemption.value), 0),
            ).where(LoyaltyRedemption.store_id == store_id)
        )
    ).one()
    tiers_rows = await load_tiers(session, store_id)
    distribution = []
    for i, t in enumerate(tiers_rows):
        cond = [LoyaltyAccount.store_id == store_id, LoyaltyAccount.lifetime_earned >= t.min_points]
        if i + 1 < len(tiers_rows):
            cond.append(LoyaltyAccount.lifetime_earned < tiers_rows[i + 1].min_points)
        distribution.append(
            {
                "name": t.name,
                "min_points": t.min_points,
                "members": int(await session.scalar(select(func.count()).select_from(LoyaltyAccount).where(*cond)) or 0),
            }
        )
    leaders = (
        await session.execute(
            select(LoyaltyAccount.user_id, LoyaltyAccount.balance, LoyaltyAccount.lifetime_earned)
            .where(LoyaltyAccount.store_id == store_id)
            .order_by(LoyaltyAccount.lifetime_earned.desc())
            .limit(top)
        )
    ).all()
    return {
        "store_id": store_id,
        "members": int(members),
        "points_outstanding": int(outstanding),
        "points_debt": int(debt),
        "points_issued": int(issued or 0),
        "points_redeemed": int(redeemed_points),
        "redemptions": int(redeemed_count),
        "value_paid": int(paid_value),
        "tiers": distribution,
        "top_members": [{"user_id": u, "balance": int(b), "lifetime_earned": int(l)} for u, b, l in leaders],
    }
