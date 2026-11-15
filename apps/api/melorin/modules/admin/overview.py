"""Admin API - overview routes (split from the former 1,900-line router; paths unchanged)."""

import logging
from fastapi import APIRouter
from sqlalchemy import func, select
from melorin.core.deps import AdminUser, Session
from melorin.kernel.models.identity import User
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
    from melorin.modules.admin import operations_center
    from melorin.modules.orders.service import count_by_status

    return {
        "orders": await count_by_status(session),
        "attention": await operations_center.attention(session),
        "active_users": await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))),
        "open_tickets": await session.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == "open")) or 0,
    }


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
            "target": row.target,
            "created_at": row.created_at,
        }
        for row in rows
    ]
