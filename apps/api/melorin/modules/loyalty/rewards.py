"""Loyalty club: rewards (see ``service.py`` for the facade and the overview)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.errors import AppError, NotFound
from melorin.domain import loyalty as rules
from melorin.domain.loyalty import LoyaltyError, Reward
from melorin.kernel.models.loyalty import (
    LoyaltyReward,
)
from melorin.kernel.models.stores import Store
from melorin.modules.loyalty.common import _fail, _json


def reward_out(r: LoyaltyReward) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "kind": r.kind,
        "value": r.value,
        "cost_points": r.cost_points,
        "stock": r.stock,
        "remaining": None if r.stock is None else max(0, r.stock - r.redeemed_count),
        "per_user_limit": r.per_user_limit,
        "redeemed_count": r.redeemed_count,
        "sort_order": r.sort_order,
        "is_active": r.is_active,
    }


async def list_rewards(session: AsyncSession, store_id: uuid.UUID, *, only_active: bool = False) -> list[LoyaltyReward]:
    q = select(LoyaltyReward).where(LoyaltyReward.store_id == store_id)
    if only_active:
        q = q.where(LoyaltyReward.is_active.is_(True))
    return list((await session.scalars(q.order_by(LoyaltyReward.sort_order, LoyaltyReward.cost_points, LoyaltyReward.created_at))).all())


async def save_reward(
    session: AsyncSession,
    store: Store,
    reward_id: uuid.UUID | None,
    *,
    name: str,
    description: str | None,
    kind: str,
    value: int,
    cost_points: int,
    stock: int | None,
    per_user_limit: int | None,
    sort_order: int,
    is_active: bool,
    actor_id: uuid.UUID,
    actor_type: str,
) -> LoyaltyReward:
    """Create (``reward_id`` None) or change a reward of ONE store; a reward id of another store is simply not found."""
    if not name.strip():
        raise AppError("LOYALTY_BAD_REWARD_NAME", "نام جایزه نامعتبر است.", 400)
    row = None
    if reward_id:
        row = await session.scalar(
            select(LoyaltyReward).where(LoyaltyReward.id == reward_id, LoyaltyReward.store_id == store.id).with_for_update()
        )
        if not row:
            raise NotFound("جایزه")
    try:
        rules.validate_reward(Reward(kind, value, cost_points, stock, row.redeemed_count if row else 0, per_user_limit, is_active))
    except LoyaltyError as e:
        raise _fail(e) from e
    before = reward_out(row) if row else None
    if not row:
        row = LoyaltyReward(store_id=store.id, redeemed_count=0)
        session.add(row)
    row.name, row.description, row.kind, row.value = name.strip(), description, kind, value
    row.cost_points, row.stock, row.per_user_limit = cost_points, stock, per_user_limit
    row.sort_order, row.is_active = sort_order, is_active
    await session.flush()
    audit.record(
        session,
        "loyalty.reward.saved",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="loyalty_reward",
        entity_id=row.id,
        store_id=store.id,
        data={"before": _json(before), "after": _json(reward_out(row))},
    )
    return row
