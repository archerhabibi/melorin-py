"""Periodic jobs. Run from cron/scheduler: health, expiry, reconciliation, backup status."""

import asyncio
import datetime as dt
import inspect
import logging
import os
from pathlib import Path

from sqlalchemy import select

from melorin.core import events, flags, integrations, settings_store
from melorin.core.db import session_factory, utcnow
from melorin.modules.identity.models import VerificationCode
from melorin.modules.notifications.models import Notification
from melorin.modules.system.models import BackupRun, OutboxEvent
from melorin.modules.vpn import service
from melorin.modules.vpn.models import Panel, VpnAccount

log = logging.getLogger("melorin.jobs")


async def _close_adapter(adapter) -> None:
    """Close adapters safely, including legacy/test adapters with sync close()."""
    close = getattr(adapter, "close", None)
    if not close:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


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
        session.add(BackupRun(status=status, location=location, size=size, details=details, created_at=started))
        await session.commit()
    if status != "succeeded":
        log.error("backup %s: %s", status, details)
    return status


async def panel_health_job(ctx=None):
    async with session_factory()() as s:
        from melorin.modules.vpn.adapters.registry import build_adapter

        panels = (await s.scalars(select(Panel).where(Panel.is_enabled.is_(True)))).all()
        for p in panels:
            adapter = None
            try:
                adapter = build_adapter(p)
                ok = await adapter.health_check()
                p.health_status, p.last_health_at = "healthy" if ok else "unhealthy", utcnow()
                p.last_health_error = None if ok else "health check returned false"
            except Exception as exc:
                p.health_status, p.last_health_at, p.last_health_error = "unhealthy", utcnow(), str(exc)[:500]
            finally:
                if adapter:
                    try:
                        await _close_adapter(adapter)
                    except Exception:
                        log.exception("panel adapter close failed panel=%s", p.id)
        await s.commit()


async def expiry_job(ctx=None):
    async with session_factory()() as s:
        now = utcnow()
        accounts = (
            await s.scalars(
                select(VpnAccount).where(VpnAccount.status == "active", VpnAccount.expires_at.is_not(None), VpnAccount.expires_at <= now)
            )
        ).all()
        for a in accounts:
            a.status = "expired"
            await events.emit(
                s,
                events.NOTIFY,
                {
                    "user_id": a.user_id,
                    "store_id": a.store_id,
                    "kind": "vpn_expired",
                    "title": "اکانت منقضی شد",
                    "body": "اکانت VPN شما منقضی شده است.",
                    "dedup_key": f"notify:expired:{a.id}",
                },
                dedup_key=f"notify:expired:{a.id}",
            )
        await s.commit()


async def near_expiry_job(ctx=None):
    async with session_factory()() as s:
        hours = int(await settings_store.get(s, "vpn.near_expiry_hours") or 48)
        now, end = utcnow(), utcnow() + dt.timedelta(hours=hours)
        accounts = (
            await s.scalars(
                select(VpnAccount).where(
                    VpnAccount.status == "active",
                    VpnAccount.near_expiry_notified.is_(False),
                    VpnAccount.expires_at > now,
                    VpnAccount.expires_at <= end,
                )
            )
        ).all()
        for a in accounts:
            a.near_expiry_notified = True
            await events.emit(
                s,
                events.NOTIFY,
                {
                    "user_id": a.user_id,
                    "store_id": a.store_id,
                    "kind": "vpn_near_expiry",
                    "title": "انقضای اکانت نزدیک است",
                    "body": "اکانت VPN شما به‌زودی منقضی می‌شود.",
                    "dedup_key": f"notify:near-expiry:{a.id}",
                },
                dedup_key=f"notify:near-expiry:{a.id}",
            )
        await s.commit()


async def reconciliation_job(ctx=None):
    async with session_factory()() as s:
        rows = (await s.scalars(select(VpnAccount.id).where(VpnAccount.status.in_(["active", "suspended"])).limit(500))).all()
        for id in rows:
            await service.reconcile(s, id)


async def privacy_retention_job(ctx=None):
    """Remove expired authentication codes while preserving financial/audit data."""
    async with session_factory()() as s:
        days = int(await settings_store.get(s, "privacy.verification_code_retention_days") or 7)
        cutoff = utcnow() - dt.timedelta(days=max(1, days))
        result = await s.execute(
            VerificationCode.__table__.delete().where(
                VerificationCode.created_at < cutoff,
                VerificationCode.expires_at < cutoff,
            )
        )
        await s.commit()
        log.info("privacy retention removed verification_codes=%s", result.rowcount or 0)
        return int(result.rowcount or 0)


async def telegram_login_gc_job(ctx=None):
    """Drop finished website-login sessions (Telegram bot approval) one day after they expired."""
    from melorin.modules.identity import telegram_web

    async with session_factory()() as s:
        removed = await telegram_web.purge_old(s)
        log.info("telegram web login sessions removed=%s", removed)
        return removed
