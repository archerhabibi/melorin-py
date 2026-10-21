"""Readiness probes (Phase 3.17). Behaviour-preserving extraction from ``app.ready``.

Each probe is small and independently testable; ``app.ready`` only composes them and shapes the HTTP response.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from sqlalchemy import func, select, text

from melorin.core.db import session_factory
from melorin.core.metrics import set_alert, set_gauge
from melorin.core.redis import get_redis
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.vpn import Panel

log = logging.getLogger("melorin.health")
WORKER_MAX_AGE_SECONDS = 15
OUTBOX_BACKLOG_THRESHOLD = 100
REDIS_TIMEOUT_SECONDS = 2.5


@dataclass
class DatabaseProbe:
    ok: bool = False
    pending: int = 0
    unhealthy_panels: int = 0
    error: str | None = None


@dataclass
class WorkerProbe:
    redis_ok: bool = False
    worker_ok: bool = False
    last_tick: str | None = None


async def probe_database() -> DatabaseProbe:
    result = DatabaseProbe()
    try:
        async with session_factory()() as session:
            await session.execute(text("SELECT 1"))
            result.pending = (
                await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status.in_(("pending", "processing"))))
                or 0
            )
            result.unhealthy_panels = (
                await session.scalar(
                    select(func.count()).select_from(Panel).where(Panel.is_enabled.is_(True), Panel.health_status != "healthy")
                )
                or 0
            )
            result.ok = True
    except Exception as exc:
        result.error = str(exc)[:200]
    return result


async def probe_worker() -> WorkerProbe:
    result = WorkerProbe()
    redis = get_redis()
    if redis is None:
        return result
    try:
        await asyncio.wait_for(redis.ping(), timeout=REDIS_TIMEOUT_SECONDS)
        result.redis_ok = True
        result.last_tick = await asyncio.wait_for(redis.get("melorin:worker:last_tick"), timeout=REDIS_TIMEOUT_SECONDS)
        age = time.time() - float(result.last_tick) if result.last_tick else None
        result.worker_ok = age is not None and 0 <= age <= WORKER_MAX_AGE_SECONDS
    except Exception as exc:
        result.redis_ok = False
        log.warning("redis health check failed: %s", type(exc).__name__)
    return result


def publish_signals(db: DatabaseProbe, worker: WorkerProbe) -> None:
    set_gauge("melorin_outbox_pending", float(db.pending))
    set_gauge("melorin_panels_unhealthy", float(db.unhealthy_panels))
    set_alert("MelorinDatabaseUnavailable", not db.ok, summary="Database unavailable", severity="critical", details=db.error or "")
    set_alert("MelorinRedisUnavailable", not worker.redis_ok, summary="Redis unavailable", severity="critical")
    set_alert(
        "MelorinWorkerStale",
        not worker.worker_ok,
        summary="Worker heartbeat stale",
        severity="critical",
        details=str(worker.last_tick or "missing"),
    )
    set_alert(
        "MelorinPanelsUnhealthy",
        db.unhealthy_panels > 0,
        summary="Enabled VPN panels unhealthy",
        severity="warning",
        details=str(db.unhealthy_panels),
    )
    set_alert(
        "MelorinOutboxBacklog",
        db.pending > OUTBOX_BACKLOG_THRESHOLD,
        summary="Outbox backlog above threshold",
        severity="warning",
        details=str(db.pending),
    )


def build_checks(db: DatabaseProbe, worker: WorkerProbe) -> dict:
    checks = {
        "database": "ok" if db.ok else "unavailable",
        "redis": "ok" if worker.redis_ok else "unavailable",
        "rate_limit": "coordinated" if worker.redis_ok else "local_degraded",
        "worker": "ok" if worker.worker_ok else "unavailable",
        "worker_last_tick": worker.last_tick,
        "outbox_pending": db.pending,
        "unhealthy_panels": db.unhealthy_panels,
    }
    if db.error:
        checks["database_error"] = db.error
    return checks
