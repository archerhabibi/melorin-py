"""Reads behind the catalog router (audit T11: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.catalog import Coupon, CouponRedemption
from melorin.kernel.models.stores import Store


async def active_store_by_slug(session: AsyncSession, slug: str) -> Store | None:
    return await session.scalar(select(Store).where(Store.slug == slug, Store.status == "active"))


async def active_store_by_domain(session: AsyncSession, domain: str) -> Store | None:
    return await session.scalar(select(Store).where(Store.domain == domain.strip().lower().rstrip("."), Store.status == "active"))


async def tls_allowed(session: AsyncSession, host: str) -> bool:
    """Caddy on-demand TLS gate: an active store hostname whose website switch is on (the main store is always served)."""
    gate = select(Store.id).where(
        Store.domain == host, Store.status == "active", or_(Store.kind != "reseller", Store.site_enabled.is_(True))
    )
    return bool(await session.scalar(gate))


async def coupons_of_store(session: AsyncSession, store_id: uuid.UUID) -> list[Coupon]:
    return list((await session.scalars(select(Coupon).where(Coupon.owner_key == str(store_id)).order_by(Coupon.created_at.desc()))).all())


async def coupon_code_exists(session: AsyncSession, store_id: uuid.UUID, code: str) -> bool:
    return bool(await session.scalar(select(Coupon.id).where(Coupon.owner_key == str(store_id), Coupon.code == code)))


async def recent_redemptions(session: AsyncSession, store_id: uuid.UUID, limit: int = 500) -> list[CouponRedemption]:
    q = select(CouponRedemption).where(CouponRedemption.store_id == store_id).order_by(CouponRedemption.created_at.desc()).limit(limit)
    return list((await session.scalars(q)).all())
