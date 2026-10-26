"""Admin API - overview routes (split from the former 1,900-line router; paths unchanged)."""

import csv
import io
import logging
import re
import uuid
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError
from melorin.kernel.models.identity import User
from melorin.modules.orders import service as order_service
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.modules.admin import bot_bindings
from melorin.kernel.models.system import BackupRun
from melorin.kernel.models.tickets import Ticket
from melorin.modules.admin.schemas import (
    CreateBotStoreBinding,
)

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


@router.get("/bot-store-bindings")
async def list_bot_store_bindings(_: AdminUser, session: Session):
    return [bot_bindings.out(row) for row in await bot_bindings.list_bindings(session)]


@router.post("/bot-store-bindings", status_code=201)
async def create_bot_store_binding(body: CreateBotStoreBinding, admin: AdminUser, session: Session):
    row = await bot_bindings.create_binding(session, body, admin)
    return bot_bindings.out(row)


@router.get("/health")
async def health(_: AdminUser, session: Session):
    from sqlalchemy import text
    from melorin.core.redis import get_redis

    await session.execute(text("SELECT 1"))
    redis = get_redis()
    worker = False
    if redis is not None:
        try:
            await redis.ping()
            worker = bool(await redis.get("melorin:worker:last_tick"))
        except Exception as exc:
            # Reported below as redis/worker "unavailable"; keep the reason in the log instead of dropping it.
            log.warning("admin health: redis check failed: %s", type(exc).__name__)
    return {"api": "ok", "database": "ok", "redis": "ok" if redis else "unavailable", "worker": "ok" if worker else "unavailable"}


@router.get("/dashboard")
async def dashboard(_: AdminUser, session: Session):
    from melorin.modules.orders.service import count_by_status

    return {
        "orders": await count_by_status(session),
        "active_users": await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))),
        "open_tickets": await session.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == "open")) or 0,
    }


@router.get("/reports/summary")
async def report_summary(_: AdminUser, session: Session):
    """Only successful payments count as sales, grouped by currency."""
    rows = (
        await session.execute(
            select(Payment.currency, func.count(Payment.id), func.sum(Payment.amount))
            .where(Payment.status == "succeeded")
            .group_by(Payment.currency)
        )
    ).all()
    return {
        "payments": [{"currency": c, "count": n, "amount": total or 0} for c, n, total in rows],
        "orders": [{"status": k, "count": v} for k, v in (await order_service.count_by_status(session)).items()],
        "open_tickets": await session.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == "open")) or 0,
        "currency_safe": True,
    }


@router.get("/reports/timeseries")
async def report_timeseries(
    _: AdminUser,
    session: Session,
    days: int = Query(default=30, ge=7, le=90),
    tz: str = Query(default="UTC", max_length=64, description="IANA time zone used to bucket days, e.g. Asia/Tehran"),
):
    """Zero-filled daily orders + per-currency sales for the dashboard chart."""
    from melorin.modules.admin.timeseries import build_timeseries

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
    from melorin.modules.admin.analytics import build_analytics

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
    from melorin.modules.admin.analytics import CSV_SECTIONS, build_analytics, to_csv_rows

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


@router.get("/operations/backups", response_model=list[dict])
async def backup_status(_: AdminUser, session: Session):
    """Read-only backup status for the Admin Web operations panel."""
    rows = (await session.scalars(select(BackupRun).order_by(BackupRun.created_at.desc()).limit(100))).all()
    return [
        {
            "id": row.id,
            "status": row.status,
            "location": row.location,
            "size": row.size,
            "details": row.details,
            "created_at": row.created_at,
        }
        for row in rows
    ]
