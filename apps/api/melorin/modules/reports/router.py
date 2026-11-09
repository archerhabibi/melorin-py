"""Read-only operational reports with explicit store scoping."""

import datetime as dt
import uuid

from fastapi import APIRouter, Query

from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.modules.reports import queries

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/stores/{store_id}/sales")
async def store_sales(store_id: uuid.UUID, _: AdminUser, session: Session):
    """Order count/total per status for one store. Unknown store -> 404, malformed id -> 422."""
    store = await queries.get_store(session, store_id)
    if not store:
        raise NotFound("فروشگاه")
    rows = await queries.sales_by_status(session, store.id)
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
    rows = await queries.payment_totals(session, date_from=date_from, date_to=date_to, limit=limit, offset=offset)
    return [{"store_id": sid, "currency": currency, "count": count, "amount": amount} for sid, currency, count, amount in rows]
