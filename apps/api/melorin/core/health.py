"""Readiness probes (Phase 3.17). Behaviour-preserving extraction from ``app.ready``.

Each probe is small and independently testable; ``app.ready`` only composes them and shapes the HTTP response.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from dataclasses import dataclass

from sqlalchemy import func, select, text

from melorin.core.db import session_factory
from melorin.core.metrics import set_alert, set_gauge
from melorin.core.redis import get_redis
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.vpn import Panel, ReconciliationIssue, VpnAccount

log = logging.getLogger("melorin.health")
WORKER_MAX_AGE_SECONDS = 15
OUTBOX_BACKLOG_THRESHOLD = 100
REDIS_TIMEOUT_SECONDS = 2.5
ISSUE_KINDS = ("missing_on_panel", "panel_unreachable", "owner_mismatch", "limits_mismatch")


@dataclass
class DatabaseProbe:
    ok: bool = False
    pending: int = 0
    unhealthy_panels: int = 0
    open_issues: dict[str, int] | None = None  # PG-04: open reconciliation issues by kind
    reconcile_lag_seconds: float | None = None  # PG-04: age of the least recently synced live account (None = nothing to sync)
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
            await _probe_reconcile(session, result)
    except Exception as exc:
        result.error = str(exc)[:200]
    return result


async def _probe_reconcile(session, result: DatabaseProbe) -> None:
    """Reconcile signals must never turn a healthy database probe into a failed one, so they are best-effort."""
    try:
        rows = (
            await session.execute(
                select(ReconciliationIssue.kind, func.count()).where(ReconciliationIssue.status == "open").group_by(ReconciliationIssue.kind)
            )
        ).all()
        result.open_issues = {kind: int(n) for kind, n in rows}
        oldest = await session.scalar(
            select(func.min(VpnAccount.last_synced_at)).where(VpnAccount.status.in_(("active", "suspended", "limited")), VpnAccount.panel_id.is_not(None))
        )
        never = await session.scalar(
            select(func.count()).select_from(VpnAccount).where(
                VpnAccount.status.in_(("active", "suspended", "limited")), VpnAccount.panel_id.is_not(None), VpnAccount.last_synced_at.is_(None)
            )
        )
        if oldest is not None and not never:
            oldest = oldest if oldest.tzinfo else oldest.replace(tzinfo=dt.UTC)
            result.reconcile_lag_seconds = max(0.0, (dt.datetime.now(dt.UTC) - oldest).total_seconds())
    except Exception as exc:
        log.warning("reconcile signals unavailable: %s", type(exc).__name__)


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
    for kind in ISSUE_KINDS:  # always publish every kind (0 when none) so a cleared issue does not leave a stale series
        set_gauge("melorin_reconcile_open_issues", float((db.open_issues or {}).get(kind, 0)), kind=kind)
    if db.reconcile_lag_seconds is not None:
        set_gauge("melorin_reconcile_lag_seconds", float(db.reconcile_lag_seconds))
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
