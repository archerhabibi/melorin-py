"""The Telegram ID of a customer account (its ``telegram`` identity), as shown in wallet and customer lists."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.identity import Identity


def of(identities) -> str | None:
    """The Telegram ID among a user's identities, if any (pure helper for views and tests)."""
    for ident in identities:
        if ident.provider == "telegram":
            return ident.subject
    return None


async def current(session: AsyncSession, user_id) -> str | None:
    row = await session.scalar(select(Identity).where(Identity.user_id == user_id, Identity.provider == "telegram"))
    return row.subject if row else None
