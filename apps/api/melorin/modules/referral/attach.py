"""referral: attach (see ``service.py`` for the facade)."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import events
from melorin.domain.order_kinds import revenue_only
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.referral import ReferralRelationship
from melorin.kernel.models.stores import Store, StoreMembership
from melorin.modules.eventcenter import topics as ec_topics


async def is_store_member(session: AsyncSession, store: Store, user_id: uuid.UUID) -> bool:
    """A person belongs to a store when he has an ACTIVE membership there (or owns it). Blocked members do not count."""
    if store.owner_user_id == user_id:
        return True
    status = await session.scalar(
        select(StoreMembership.status).where(StoreMembership.store_id == store.id, StoreMembership.user_id == user_id)
    )
    return status == "active"


async def has_store_history(session: AsyncSession, store_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """True when the customer already bought (a real, non-test order) in THIS store: he is no longer 'new here'."""
    return bool(
        await session.scalar(
            select(Order.id).where(Order.user_id == user_id, Order.store_id == store_id, revenue_only(Order.kind)).limit(1)
        )
    )


_MAX_CHAIN_DEPTH = 64  # far beyond any real invite chain; only bounds the walk so a corrupted graph can never loop it forever


async def _closes_a_loop(session: AsyncSession, store_id: uuid.UUID, *, referrer_id: uuid.UUID, referred_id: uuid.UUID) -> bool:
    """True when ``referred_id`` already sits ABOVE ``referrer_id`` in this store's invite chain.

    Walks the referrer's own referrer, then that person's referrer, and so on, inside ONE store only (the graphs of different
    stores are independent). The simple two-person loop (A invited B, B tries to invite A) is just the first step of this walk.
    """
    seen = {referrer_id}
    current = referrer_id
    for _ in range(_MAX_CHAIN_DEPTH):
        parent = await session.scalar(
            select(ReferralRelationship.referrer_user_id).where(
                ReferralRelationship.store_id == store_id, ReferralRelationship.referred_user_id == current
            )
        )
        if parent is None:
            return False
        if parent == referred_id:
            return True
        if parent in seen:
            return False  # an old ring that is not about the newcomer: nothing new is closed by this link
        seen.add(parent)
        current = parent
    return False


async def attach(session: AsyncSession, store_id: uuid.UUID, referred: User, referrer: User | None) -> bool:
    """Record ``referrer`` as the first-touch referrer of ``referred`` INSIDE ``store_id``. Returns True when a row was added.

    A referral is valid only inside one store: the store must be active, the referrer must be a member of it (a code from
    another store's customer is not a referral here), the newcomer must not have bought here yet (no hijacking of an existing
    customer) and the first relationship of that store wins. Later links are ignored silently (no oracle for the client).
    """
    if not referrer or referrer.id == referred.id:
        return False
    store = await session.get(Store, store_id)
    if not store or store.status != "active":
        return False
    if not await is_store_member(session, store, referrer.id):
        return False
    exists = await session.scalar(
        select(ReferralRelationship.id).where(
            ReferralRelationship.store_id == store_id, ReferralRelationship.referred_user_id == referred.id
        )
    )
    if exists:
        return False
    if await has_store_history(session, store_id, referred.id):
        return False
    if await _closes_a_loop(session, store_id, referrer_id=referrer.id, referred_id=referred.id):
        return False  # a -> b -> ... -> referrer: making the referrer a's referrer would pay rewards in a circle
    try:  # two sign-ups of the same person racing each other: the unique key lets one win, the other is simply "not attached"
        async with session.begin_nested():
            session.add(ReferralRelationship(store_id=store_id, referrer_user_id=referrer.id, referred_user_id=referred.id))
            await session.flush()
    except IntegrityError:
        return False
    await events.emit(
        session,
        events.EVENT_CENTER,
        {"store_id": store_id, "topic": ec_topics.AFFILIATE, "text": "👥 معرف جدید ثبت شد\nیک کاربر با لینک معرفی ثبت‌نام کرد."},
        dedup_key=f"ec:affiliate:attach:{store_id}:{referred.id}",
    )
    return True
