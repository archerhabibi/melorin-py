"""Panel backup status (PG-16): is the PasarGuard panel itself backed up, how fresh, and does the last copy leave the server?

Melorin's own database has ``backup_job``; the panel's database and data directory (certificates, node CA, env) are a different failure
domain: lose the panel and Melorin can rebuild accounts from its own records only through reconcile (see ``docs/RUNBOOK.md``), but the
panel's users, usage history and node trust come back only from this backup. Read-only: the status never touches the panel."""

from __future__ import annotations

import datetime as dt
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.kernel.models.system import BackupRun
from melorin.modules.vpn.panel_metrics import PANEL_BACKUP_MAX_AGE, _aware, panel_backup_configured

RUNS_SHOWN = 20


def _run_out(run: BackupRun) -> dict:
    """One run for the admin: the artifact's server path is never exposed, only its file name."""
    name = (run.location or "").rsplit("/", 1)[-1] or None
    return {
        "id": run.id,
        "status": run.status,
        "size": run.size,
        "file": name,
        "details": (run.details or "")[:300],
        "created_at": run.created_at,
    }


async def status(session: AsyncSession, now: dt.datetime | None = None) -> dict:
    now = now or utcnow()
    runs = (
        await session.scalars(select(BackupRun).where(BackupRun.target == "panel").order_by(BackupRun.created_at.desc()).limit(RUNS_SHOWN))
    ).all()
    ok = next((r for r in runs if r.status == "succeeded"), None)
    last_ok = _aware(ok.created_at) if ok else None
    age = max((now - last_ok).total_seconds(), 0.0) if last_ok else None
    configured = panel_backup_configured()
    if not configured and not runs:
        state = "not_configured"
    elif age is None or age > PANEL_BACKUP_MAX_AGE.total_seconds():
        state = "stale"
    else:
        state = "ok"
    return {
        "state": state,
        "configured": configured,
        "database_configured": bool(os.getenv("MELORIN_PANEL_BACKUP_DATABASE_URL")),
        "paths_configured": bool(os.getenv("MELORIN_PANEL_BACKUP_PATHS")),
        "last_success_at": last_ok,
        "age_seconds": age,
        "max_age_hours": int(PANEL_BACKUP_MAX_AGE.total_seconds() // 3600),
        "runs": [_run_out(r) for r in runs],
    }
