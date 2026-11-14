"""Backup jobs: encrypted local backup (+S3) and the per-panel backup."""

import asyncio
import functools
import logging
import os
from pathlib import Path


from melorin.core import integrations
from melorin.core.db import session_factory, utcnow
from melorin.kernel.models.system import BackupRun
from melorin.modules.eventcenter import rules as event_center_rules
from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter
from melorin.worker.wrap import tracked_job

_close_strict = functools.partial(close_adapter, strict=True)  # worker jobs keep raising on close failure
log = logging.getLogger("melorin.jobs")




@tracked_job(lock_ttl=910)
async def backup_job(ctx=None):
    """Always write an encrypted LOCAL backup; also copy it to S3 when enabled in the Admin panel."""
    root = Path(os.getenv("MELORIN_PROJECT_ROOT", "/app"))
    script = root / "scripts" / "backup_secure.sh"
    started = utcnow()
    status, location, details, size = "failed", None, None, None
    env = dict(os.environ)
    try:
        async with session_factory()() as session:
            s3 = await integrations.get_backup_s3(session)
        if integrations.backup_s3_ready(s3):
            env.update(integrations.rclone_env(s3))
            env["MELORIN_BACKUP_OFFSITE_URI"] = integrations.rclone_uri(s3)
        proc = await asyncio.create_subprocess_exec(
            str(script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(root),
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=900)
        lines = stdout.decode(errors="replace").strip().splitlines()
        if proc.returncode in (0, 3) and lines:
            location = lines[-1]
            size = Path(location).stat().st_size if Path(location).exists() else None
            if proc.returncode == 0:
                status = "succeeded"
                details = "encrypted artifact and checksum verification completed" + (
                    "; copied to S3" if env.get("MELORIN_BACKUP_OFFSITE_URI") else "; local only"
                )
            else:  # exit 3: local backup is fine, the off-site copy failed
                status = "partial"
                details = "local backup OK but S3 upload failed: " + stderr.decode(errors="replace")[-1500:]
        else:
            details = stderr.decode(errors="replace")[-2000:]
    except Exception as exc:
        details = str(exc)[:2000]
    async with session_factory()() as session:
        run = BackupRun(status=status, location=location, size=size, details=details, created_at=started)
        session.add(run)
        await session.flush()  # the run id is the dedup key of its Event Center notice
        await event_center_rules.notify_backup(session, run)
        await session.commit()
    if status != "succeeded":
        log.error("backup %s: %s", status, details)
    return status



@tracked_job(lock_ttl=910)
async def panel_backup_job(ctx=None):
    """Daily: encrypted backup of the PasarGuard panel (its database and data directory), recorded as ``BackupRun(target="panel")`` (PG-16).

    Does nothing (no run, no alert) until ``MELORIN_PANEL_BACKUP_DATABASE_URL`` and/or ``MELORIN_PANEL_BACKUP_PATHS`` is set: a panel that is
    not backed up by Melorin is "not in use", not "stale". Same exit-code protocol as ``backup_job`` (0 ok, 3 local ok but off-site failed)."""
    if not (os.getenv("MELORIN_PANEL_BACKUP_DATABASE_URL") or os.getenv("MELORIN_PANEL_BACKUP_PATHS")):
        return "not_configured"
    root = Path(os.getenv("MELORIN_PROJECT_ROOT", "/app"))
    script = root / "scripts" / "backup_panel.sh"
    started = utcnow()
    status, location, details, size = "failed", None, None, None
    env = dict(os.environ)
    try:
        async with session_factory()() as session:
            s3 = await integrations.get_backup_s3(session)
        if integrations.backup_s3_ready(s3):
            env.update(integrations.rclone_env(s3))
            env["MELORIN_BACKUP_OFFSITE_URI"] = integrations.rclone_uri(s3)
        proc = await asyncio.create_subprocess_exec(
            str(script), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(root), env=env
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=900)
        lines = stdout.decode(errors="replace").strip().splitlines()
        if proc.returncode in (0, 3) and lines:
            location = lines[-1]
            size = Path(location).stat().st_size if Path(location).exists() else None
            if proc.returncode == 0:
                status = "succeeded"
                details = "panel backup encrypted and verified" + (
                    "; copied to S3" if env.get("MELORIN_BACKUP_OFFSITE_URI") else "; local only"
                )
            else:
                status = "partial"
                details = "local panel backup OK but S3 upload failed: " + stderr.decode(errors="replace")[-1500:]
        else:
            details = stderr.decode(errors="replace")[-2000:]
    except Exception as exc:
        details = str(exc)[:2000]
    async with session_factory()() as session:
        run = BackupRun(status=status, location=location, size=size, details=details, created_at=started, target="panel")
        session.add(run)
        await session.flush()
        await event_center_rules.notify_backup(session, run)
        await session.commit()
    if status != "succeeded":
        log.error("panel backup %s: %s", status, details)
    return status


