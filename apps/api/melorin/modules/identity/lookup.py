"""Identity/user lookups shared by the identity service and the Google sign-in module (no other dependencies)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.identity import Identity, User


async def find_identity_any(session: AsyncSession, provider: str, subject: str) -> Identity | None:
    """The row for this provider identity whatever its state (a revoked row still owns the unique ``(provider, subject)`` slot)."""
    return await session.scalar(select(Identity).where(Identity.provider == provider, Identity.subject == subject))


async def find_identity(session: AsyncSession, provider: str, subject: str) -> Identity | None:
    """The ACTIVE identity: a revoked login method can no longer sign anybody in or count as attached (docs/25)."""
    return await session.scalar(
        select(Identity).where(Identity.provider == provider, Identity.subject == subject, Identity.status == "active")
    )


async def email_taken(session: AsyncSession, email: str) -> bool:
    return (await session.scalar(select(User.id).where(User.email == email))) is not None
