"""Identity/user lookups shared by the identity service and the Google sign-in module (no other dependencies)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.identity import Identity, User


async def find_identity(session: AsyncSession, provider: str, subject: str) -> Identity | None:
    return await session.scalar(select(Identity).where(Identity.provider == provider, Identity.subject == subject))


async def email_taken(session: AsyncSession, email: str) -> bool:
    return (await session.scalar(select(User.id).where(User.email == email))) is not None
