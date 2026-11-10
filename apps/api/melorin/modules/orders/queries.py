"""Reads behind the orders router (audit T11: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.orders import Order


async def recent_for_scope(session: AsyncSession, scope: list[ColumnElement[bool]], limit: int = 100) -> list[Order]:
    return list((await session.scalars(select(Order).where(*scope).order_by(Order.created_at.desc()).limit(limit))).all())
