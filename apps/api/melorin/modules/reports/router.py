"""Read-only operational reports with explicit store scoping."""

import datetime as dt
import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.modules.orders.models import Order
from melorin.modules.payments.models import Payment
from melorin.modules.stores.models import Store

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/stores/{store_id}/sales")
async def store_sales(store_id: uuid.UUID, _: AdminUser, session: Session):
    """Order count/total per status for one store. Unknown store -> 404, malformed id -> 422."""
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    rows = (
        await session.execute(
            select(Order.status, func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
            .where(Order.store_id == store.id)
            .group_by(Order.status)
            .order_by(Order.status)
        )
    ).all()
    return {
        "store_id": store.id,
        "currency": store.currency,
        "orders": [{"status": status, "count": count, "total": total} for status, count, total in rows],
    }


@router.get("/payments")
async def payment_totals(
    _: AdminUser,
    session: Session,
    date_from: dt.date | None = Query(default=None, description="first sale day, inclusive (UTC)"),
    date_to: dt.date | None = Query(default=None, description="last sale day, inclusive (UTC)"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Succeeded-payment totals per (store, currency), optionally limited to a UTC date range and paginated.

    Sales are dated like the dashboard chart: review time when present, creation time otherwise.
    """
    if date_from and date_to and date_from > date_to:
        raise AppError("INVALID_DATE_RANGE", "date_from نباید بعد از date_to باشد.", 422)
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
    return [{"store_id": sid, "currency": currency, "count": count, "amount": amount} for sid, currency, count, amount in rows]
