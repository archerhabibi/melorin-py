"""Read-only report queries behind ``/reports`` (audit T11/T67: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.domain.order_kinds import not_manual
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import Store


async def get_store(session: AsyncSession, store_id: uuid.UUID) -> Store | None:
    return await session.get(Store, store_id)


async def sales_by_status(session: AsyncSession, store_id: uuid.UUID) -> list[tuple[str, int, int]]:
    """(status, count, total) per order status for one store, manual orders excluded."""
    rows = (
        await session.execute(
            select(Order.status, func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
            .where(Order.store_id == store_id, not_manual(Order.kind))
            .group_by(Order.status)
            .order_by(Order.status)
        )
    ).all()
    return [(status, count, total) for status, count, total in rows]


async def payment_totals(
    session: AsyncSession, *, date_from: dt.date | None, date_to: dt.date | None, limit: int, offset: int
) -> list[tuple[uuid.UUID, str, int, int]]:
    """Succeeded-payment totals per (store, currency); sales are dated by review time, creation time otherwise (UTC days)."""
    sale_at = func.coalesce(Payment.reviewed_at, Payment.created_at)
    query = select(Payment.store_id, Payment.currency, func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.status == "succeeded"
    )
    if date_from:
        query = query.where(sale_at >= dt.datetime.combine(date_from, dt.time.min, tzinfo=dt.UTC))
    if date_to:
        query = query.where(sale_at < dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC))
    rows = (
        await session.execute(
            query.group_by(Payment.store_id, Payment.currency).order_by(Payment.store_id, Payment.currency).limit(limit).offset(offset)
        )
    ).all()
    return [(sid, currency, count, amount) for sid, currency, count, amount in rows]
