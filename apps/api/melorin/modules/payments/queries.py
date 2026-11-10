"""Reads behind the payments router (audit T11: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.payments import Payment


async def recent_for_scope(session: AsyncSession, scope: list[ColumnElement[bool]], limit: int = 100) -> list[Payment]:
    return list((await session.scalars(select(Payment).where(*scope).order_by(Payment.created_at.desc()).limit(limit))).all())
