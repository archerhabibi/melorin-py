"""Person queries and the lazy creation of a Person for legacy accounts (new accounts get one from the ORM insert hook)."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.errors import AppError
from melorin.kernel.models.identity import Identity, User
from melorin.kernel.models.person import Person


async def ensure_person(session: AsyncSession, user: User) -> Person:
    person = await session.get(Person, user.person_id) if user.person_id else None
    if person is None:
        person = Person()
        session.add(person)
        await session.flush()
        user.person_id = person.id
    await session.execute(update(Identity).where(Identity.user_id == user.id, Identity.person_id.is_(None)).values(person_id=person.id))
    return person


async def accounts_of(session: AsyncSession, person_id: uuid.UUID) -> list[User]:
    return list((await session.scalars(select(User).where(User.person_id == person_id).order_by(User.created_at, User.id))).all())


async def identities_of(session: AsyncSession, person_id: uuid.UUID, *, active_only: bool = True) -> list[Identity]:
    q = select(Identity).where(Identity.person_id == person_id).order_by(Identity.created_at, Identity.id)
    if active_only:
        q = q.where(Identity.status == "active")
    return list((await session.scalars(q)).all())


async def active_provider_counts(session: AsyncSession, person_id: uuid.UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ident in await identities_of(session, person_id):
        counts[ident.provider] = counts.get(ident.provider, 0) + 1
    return counts


async def lock_person(session: AsyncSession, person_id: uuid.UUID) -> Person:
    person = await session.get(Person, person_id, with_for_update=True)
    if person is None:
        raise AppError("PERSON_NOT_FOUND", "پروفایل یافت نشد.", 404)
    return person


def ensure_usable(person: Person) -> None:
    if person.status != "active":
        raise AppError("PERSON_RESTRICTED", "این پروفایل در حال حاضر امکان تغییر اتصال‌ها را ندارد.", 403)
