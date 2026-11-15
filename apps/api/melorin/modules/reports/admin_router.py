"""Admin API - business reports (r15: the reports module owns every /admin/reports/* route and its calculation).

The admin overview (dashboard, health) only composes; sales summary, the daily series, analytics and the CSV exports are computed here
and nowhere else. Paths, methods and payloads are unchanged.
"""

import csv
import io
import re
import uuid

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError
from melorin.kernel.models.orders import Order

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/reports/summary")
async def report_summary(_: AdminUser, session: Session):
    """Only successful payments count as sales, grouped by currency (computed by the reports module)."""
    from melorin.modules.reports.summary import build_summary

    return await build_summary(session)


@router.get("/reports/timeseries")
async def report_timeseries(
    _: AdminUser,
    session: Session,
    days: int = Query(default=30, ge=7, le=90),
    tz: str = Query(default="UTC", max_length=64, description="IANA time zone used to bucket days, e.g. Asia/Tehran"),
):
    """Zero-filled daily orders + per-currency sales for the dashboard chart."""
    from melorin.modules.reports.timeseries import build_timeseries

    try:
        return await build_timeseries(session, days, tz=tz)
    except ValueError as exc:
        raise AppError("INVALID_TIMEZONE", "منطقه زمانی نامعتبر است.", 422) from exc


@router.get("/reports/analytics")
async def report_analytics(
    _: AdminUser,
    session: Session,
    days: int = Query(default=30, ge=7, le=90),
    tz: str = Query(default="UTC", max_length=64, description="IANA time zone used to bucket days, e.g. Asia/Tehran"),
    currency: str | None = Query(default=None, min_length=2, max_length=8, description="report currency (default: top-selling one)"),
    store_id: uuid.UUID | None = Query(default=None, description="limit orders and payments to one store"),
):
    """Everything the Reports & charts screen needs in one currency-safe payload (KPIs vs previous period, series, breakdowns)."""
    from melorin.modules.reports.analytics import build_analytics

    try:
        return await build_analytics(session, days, tz=tz, currency=currency.upper() if currency else None, store_id=store_id)
    except ValueError as exc:
        raise AppError("INVALID_TIMEZONE", "منطقه زمانی نامعتبر است.", 422) from exc


@router.get("/reports/analytics.csv")
async def export_analytics(
    _: AdminUser,
    session: Session,
    section: str = Query(default="daily", description="daily | products | stores | methods"),
    days: int = Query(default=30, ge=7, le=90),
    tz: str = Query(default="UTC", max_length=64),
    currency: str | None = Query(default=None, min_length=2, max_length=8),
    store_id: uuid.UUID | None = Query(default=None),
):
    """CSV of one analytics section (UTF-8 with BOM so Excel opens Persian names correctly)."""
    from melorin.modules.reports.analytics import CSV_SECTIONS, build_analytics, to_csv_rows

    if section not in CSV_SECTIONS:
        raise AppError("INVALID_SECTION", "بخش گزارش نامعتبر است.", 422)
    try:
        payload = await build_analytics(session, days, tz=tz, currency=currency.upper() if currency else None, store_id=store_id)
    except ValueError as exc:
        raise AppError("INVALID_TIMEZONE", "منطقه زمانی نامعتبر است.", 422) from exc
    head, rows = to_csv_rows(payload, section)
    # the currency echoes the query when no data matched it: keep header-unsafe characters out of the file name
    safe_currency = re.sub(r"[^A-Za-z0-9]", "", str(payload["currency"]))[:8] or "XXX"
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(head)
    for row in rows:
        # Spreadsheet formula injection: names come from admins/resellers, so neutralise leading = + - @ in text cells.
        writer.writerow([f"'{c}" if isinstance(c, str) and c[:1] in ("=", "+", "-", "@", "\t", "\r") else c for c in row])
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=melorin-{section}-{safe_currency}-{days}d.csv"},
    )


@router.get("/reports/orders.csv")
async def export_orders(_: AdminUser, session: Session, status: str | None = Query(default=None)):
    q = select(Order).order_by(Order.created_at.desc()).limit(5000)
    if status:
        q = q.where(Order.status == status)
    rows = (await session.scalars(q)).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "number", "store_id", "status", "total", "currency", "created_at"])
    for o in rows:
        writer.writerow([o.id, o.number, o.store_id, o.status, o.total, o.currency, o.created_at.isoformat()])
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=melorin-orders.csv"},
    )
