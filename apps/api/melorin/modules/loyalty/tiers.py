"""Loyalty club: tiers (see ``service.py`` for the facade and the overview)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.domain.loyalty import Tier
from melorin.kernel.models.loyalty import (
    LoyaltyTier,
)


async def load_tiers(session: AsyncSession, store_id: uuid.UUID) -> list[LoyaltyTier]:
    q = select(LoyaltyTier).where(LoyaltyTier.store_id == store_id).order_by(LoyaltyTier.min_points)
    return list((await session.scalars(q)).all())


def ladder(rows: list[LoyaltyTier]) -> list[Tier]:
    return [Tier(r.name, r.min_points, r.multiplier_bp) for r in rows]


def tier_out(t: LoyaltyTier) -> dict:
    return {"id": t.id, "name": t.name, "min_points": t.min_points, "multiplier_bp": t.multiplier_bp}
