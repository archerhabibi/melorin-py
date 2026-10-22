"""Admin API - overview routes (split from the former 1,900-line router; paths unchanged)."""

import csv
import io
import logging
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
