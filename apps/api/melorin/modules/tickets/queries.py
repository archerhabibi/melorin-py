"""Reads behind the tickets router (audit T11: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.tickets import Ticket


async def mine(session: AsyncSession, user_id: uuid.UUID, store_id: uuid.UUID) -> list[Ticket]:
    """The customer's own tickets of one store, most recently updated first."""
    q = select(Ticket).where(Ticket.user_id == user_id, Ticket.store_id == store_id).order_by(Ticket.updated_at.desc())
    return list((await session.scalars(q)).all())
