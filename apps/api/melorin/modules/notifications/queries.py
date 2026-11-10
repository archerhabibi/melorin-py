"""Reads/writes behind the customer notification endpoints (audit T11: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.kernel.models.notifications import Notification


async def list_for_store(
    session: AsyncSession, scope: list[ColumnElement[bool]], *, unread_only: bool, limit: int
) -> tuple[int, list[Notification]]:
    """Newest first (``limit`` clamped to 1..200) plus the unread count for the same store scope."""
    q = select(Notification).where(*scope).order_by(Notification.created_at.desc()).limit(min(max(limit, 1), 200))
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    unread = await session.scalar(select(func.count()).select_from(Notification).where(*scope, Notification.read_at.is_(None)))
    return unread or 0, list((await session.scalars(q)).all())


async def mark_all_read(session: AsyncSession, scope: list[ColumnElement[bool]]) -> None:
    await session.execute(update(Notification).where(*scope, Notification.read_at.is_(None)).values(read_at=utcnow()))
