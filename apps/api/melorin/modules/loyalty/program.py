"""Loyalty club: program (see ``service.py`` for the facade and the overview)."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.domain import loyalty as rules
from melorin.domain.loyalty import LoyaltyError, Program, Tier
from melorin.kernel.models.loyalty import (
    LoyaltyProgram,
    LoyaltyTier,
)
from melorin.kernel.models.stores import Store
from melorin.modules.loyalty.common import _fail
from melorin.modules.loyalty.tiers import load_tiers, tier_out


# ---------------------------------------------------------------- program and ladder
def program_rules(row: LoyaltyProgram) -> Program:
    return Program(
        earn_unit=row.earn_unit,
        points_per_unit=row.points_per_unit,
        max_points_per_order=row.max_points_per_order,
        first_order_bonus=row.first_order_bonus,
        referral_bonus=row.referral_bonus,
    )


async def get_program(session: AsyncSession, store_id: uuid.UUID) -> LoyaltyProgram | None:
    return await session.scalar(select(LoyaltyProgram).where(LoyaltyProgram.store_id == store_id))


async def ensure_program(session: AsyncSession, store: Store) -> LoyaltyProgram:
    """The store's program row (created disabled with the default ladder on first use)."""
    row = await get_program(session, store.id)
    if row:
        return row
    try:  # two first requests racing each other: the unique key lets one win
        async with session.begin_nested():
            row = LoyaltyProgram(store_id=store.id, is_enabled=False)
            session.add(row)
            await session.flush()
    except IntegrityError:
        return await get_program(session, store.id)  # type: ignore[return-value]
    if not await load_tiers(session, store.id):
        session.add_all(
            LoyaltyTier(store_id=store.id, name=t.name, min_points=t.min_points, multiplier_bp=t.multiplier_bp) for t in rules.DEFAULT_TIERS
        )
        await session.flush()
    return row


def program_out(row: LoyaltyProgram | None) -> dict:
    if row is None:
        return {
            "enabled": False,
            "earn_unit": None,
            "points_per_unit": None,
            "max_points_per_order": None,
            "first_order_bonus": 0,
            "referral_bonus": 0,
        }
    return {
        "enabled": row.is_enabled,
        "earn_unit": row.earn_unit,
        "points_per_unit": row.points_per_unit,
        "max_points_per_order": row.max_points_per_order,
        "first_order_bonus": row.first_order_bonus,
        "referral_bonus": row.referral_bonus,
    }


async def upsert_program(
    session: AsyncSession,
    store: Store,
    *,
    enabled: bool,
    earn_unit: int,
    points_per_unit: int,
    max_points_per_order: int | None,
    first_order_bonus: int,
    referral_bonus: int,
    actor_id: uuid.UUID,
    actor_type: str,
) -> LoyaltyProgram:
    """Change the earning rules of ONE store. The caller has already proven it may act on ``store``; the caller commits."""
    program = Program(earn_unit, points_per_unit, max_points_per_order, first_order_bonus, referral_bonus)
    try:
        rules.validate_program(program)
    except LoyaltyError as e:
        raise _fail(e) from e
    row = await ensure_program(session, store)
    before = program_out(row)
    row.is_enabled, row.earn_unit, row.points_per_unit = enabled, earn_unit, points_per_unit
    row.max_points_per_order, row.first_order_bonus, row.referral_bonus = max_points_per_order, first_order_bonus, referral_bonus
    await session.flush()
    audit.record(
        session,
        "loyalty.program.saved",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="loyalty_program",
        entity_id=row.id,
        store_id=store.id,
        data={"before": before, "after": program_out(row)},
    )
    return row


async def replace_tiers(
    session: AsyncSession, store: Store, tiers: list[Tier], *, actor_id: uuid.UUID, actor_type: str
) -> list[LoyaltyTier]:
    """Replace the whole ladder of ONE store at once, so it is always valid (starts at 0, thresholds rise). Caller commits."""
    try:
        rules.validate_tiers(tiers)
    except LoyaltyError as e:
        raise _fail(e) from e
    await ensure_program(session, store)
    old = await load_tiers(session, store.id)
    before = [tier_out(t) | {"id": str(t.id)} for t in old]
    for t in old:
        await session.delete(t)
    await session.flush()
    rows = [
        LoyaltyTier(store_id=store.id, name=t.name.strip(), min_points=t.min_points, multiplier_bp=t.multiplier_bp)
        for t in rules.sort_tiers(tiers)
    ]
    session.add_all(rows)
    await session.flush()
    audit.record(
        session,
        "loyalty.tiers.saved",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="loyalty_program",
        entity_id=store.id,
        store_id=store.id,
        data={"before": before, "after": [{"name": r.name, "min_points": r.min_points, "multiplier_bp": r.multiplier_bp} for r in rows]},
    )
    return rows
