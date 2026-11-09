"""Reads behind the loyalty router (audit T11: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.loyalty import LoyaltyRedemption


async def my_redemptions(session: AsyncSession, store_id: uuid.UUID, user_id: uuid.UUID, limit: int) -> list[LoyaltyRedemption]:
    q = (
        select(LoyaltyRedemption)
        .where(LoyaltyRedemption.store_id == store_id, LoyaltyRedemption.user_id == user_id)
        .order_by(LoyaltyRedemption.created_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(q)).all())
