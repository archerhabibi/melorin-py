"""Reads behind the referral router (audit T11: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.referral import Commission, CommissionRule, ReferralRelationship


async def invited_count(session: AsyncSession, rel_scope: list[ColumnElement[bool]] | tuple[ColumnElement[bool], ...]) -> int:
    return len((await session.scalars(select(ReferralRelationship.id).where(*rel_scope))).all())


async def commissions(session: AsyncSession, com_scope, limit: int) -> list[Commission]:
    return list((await session.scalars(select(Commission).where(*com_scope).order_by(Commission.created_at.desc()).limit(limit))).all())


async def first_relationship(session: AsyncSession, rel_scope) -> ReferralRelationship | None:
    return await session.scalar(select(ReferralRelationship).where(*rel_scope))


async def relationship_count(session: AsyncSession, rel_scope) -> int:
    return len((await session.scalars(select(ReferralRelationship).where(*rel_scope))).all())


async def all_rules(session: AsyncSession) -> list[CommissionRule]:
    return list((await session.scalars(select(CommissionRule).order_by(CommissionRule.store_id, CommissionRule.kind))).all())
