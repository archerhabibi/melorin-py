"""Reads behind the tickets router (audit T11: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.tickets import Ticket


async def mine(session: AsyncSession, user_id: uuid.UUID, store_id: uuid.UUID) -> list[Ticket]:
    """The customer's own tickets of one store, most recently updated first."""
    q = select(Ticket).where(Ticket.user_id == user_id, Ticket.store_id == store_id).order_by(Ticket.updated_at.desc())
    return list((await session.scalars(q)).all())


OPEN_STATUS = "open"


async def count_open(session: AsyncSession) -> int:
    """THE definition of an "open ticket" (awaiting staff). Admin Overview and the Operations Center both read it from here."""
    return int(await session.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == OPEN_STATUS)) or 0)
