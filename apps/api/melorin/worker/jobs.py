"""Periodic jobs. Run from cron/scheduler: health, expiry, reconciliation, backup status."""

import asyncio
import datetime as dt
import inspect
import logging
import os
from pathlib import Path

from sqlalchemy import and_, or_, select

from melorin.core import integrations, settings_store
from melorin.core.db import session_factory, utcnow
from melorin.kernel.models.identity import VerificationCode
from melorin.kernel.models.system import BackupRun
from melorin.modules.eventcenter import report as event_center_report
from melorin.modules.eventcenter import rules as event_center_rules
from melorin.modules.vpn import capabilities, capacity, health, live, notices, panel_events, reconcile, sync
from melorin.kernel.models.vpn import Panel, VpnAccount

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
        run = BackupRun(status=status, location=location, size=size, details=details, created_at=started)
        session.add(run)
        await session.flush()  # the run id is the dedup key of its Event Center notice
        await event_center_rules.notify_backup(session, run)
        await session.commit()
    if status != "succeeded":
        log.error("backup %s: %s", status, details)
    return status


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


async def daily_report_job(ctx=None):
    """Queue the Event Center nightly summary (one per group). Safe to run twice: the report is deduplicated per Tehran day."""
    async with session_factory()() as session:
        queued = await event_center_report.run(session)
        await session.commit()
    return queued


async def store_digest_job(ctx=None):
    """Daily: the opt-in digest for store owners (PG-06). Says only what Melorin owns (notices sent, open discrepancies, sell blocks)."""
    from melorin.modules.vpn import digest

    async with session_factory()() as session:
        queued = await digest.run(session)
        await session.commit()
    return queued


async def panel_health_job(ctx=None):
    """Every 2 minutes: panel health in two layers (PG-01). The panel must answer AND have a connected node; a failing node
    alone makes the panel ``degraded`` (still selling), no connected node makes it ``unhealthy`` (leaves server selection)."""
    async with session_factory()() as s:
        from melorin.modules.vpn.adapters.registry import build_adapter

        panels = (await s.scalars(select(Panel).where(Panel.is_enabled.is_(True)))).all()
        for p in panels:
            adapter = None
            result = health.HealthResult(health.UNHEALTHY, "unknown")
            capacity_changes: list = []
            try:
                adapter = build_adapter(p)
                result = await health.check_panel(s, p, adapter)
                if result.status != health.UNHEALTHY and capabilities.is_stale(
                    p
                ):  # hourly: permissions change when the panel role is edited
                    try:
                        await capabilities.refresh(p, adapter)
                    except Exception:  # a probe problem must never flip the panel to unhealthy
                        log.warning("panel capability refresh failed panel=%s", p.id, exc_info=True)
                if result.status != health.UNHEALTHY:  # PG-08: layer 3, the destinations' real group/host/node state and fill level
                    try:
                        capacity_changes = await capacity.refresh_panel(s, p, adapter)
                    except Exception:  # never let a capacity problem change the panel's verdict
                        log.warning("panel capacity refresh failed panel=%s", p.id, exc_info=True)
            except Exception as exc:
                result = health.HealthResult(
                    health.UNHEALTHY, str(exc)[:500], {"layer": 1, "sellable": False, "checked_at": utcnow().isoformat()}
                )
            finally:
                if adapter:
                    try:
                        await _close_adapter(adapter)
                    except Exception:
                        log.exception("panel adapter close failed panel=%s", p.id)
            previous = health.apply(p, result)
            await event_center_rules.notify_panel_health(s, p, previous)
            await event_center_rules.notify_panel_nodes(s, p, result.node_changes)
            await event_center_rules.notify_server_capacity(s, p, capacity_changes)
        await s.commit()


async def panel_metrics_job(ctx=None):
    """Every 2 minutes: one live reading per panel (latency, resources, users, online) for the /metrics gauges (PG-14)."""
    from melorin.modules.vpn import panel_metrics

    async with session_factory()() as s:
        done = await panel_metrics.run_snapshots(s, close_adapter=_close_adapter)
        await s.commit()
    return done


async def panel_settings_drift_job(ctx=None):
    """Hourly: compare each PasarGuard panel's settings with what Melorin needs. READ-ONLY: it reports, an admin decides (PG-15)."""
    from melorin.modules.vpn import settings_drift

    async with session_factory()() as s:
        done = await settings_drift.run_all(s, close_adapter=_close_adapter)
        await s.commit()
    return done


EXPIRY_LIVE_BATCH = 200  # overdue panel accounts re-read per run (the rest wait for the next run)


async def expiry_job(ctx=None):
    """Overdue accounts. Mediator rule: the PANEL decides ``expired``, not Melorin's clock.

    * an account on a panel is only a *candidate* once its SOLD expiry has passed; it is re-read live from the panel and the
      panel's answer (status, current expiry) is applied. A panel that is down, or an account that is missing there, changes
      nothing (the reconcile job records the issue); a renewal done on the panel simply moves the expiry forward;
    * an account without a panel (manual / legacy) has no other source, so the local clock still applies to it;
    * ``on_hold`` accounts (waiting for their first connection) have no running clock: the live read says so, the status stays
      ``active``, and a read younger than ``sync.FRESH_FOR`` is not repeated.
    """
    async with session_factory()() as s:
        now = utcnow()
        overdue = and_(
            VpnAccount.status == "active",
            VpnAccount.sold_expires_at.is_not(None),
            VpnAccount.sold_expires_at <= now,
        )
        not_just_read = or_(VpnAccount.last_synced_at.is_(None), VpnAccount.last_synced_at < now - sync.FRESH_FOR)
        # accounts without a panel: the only clock there is
        for a in (await s.scalars(select(VpnAccount).where(overdue, VpnAccount.panel_id.is_(None)))).all():
            a.status = "expired"
            await notices.expired(s, a)
        await s.commit()
        # accounts on a panel: ask the panel (oldest read first, bounded per run)
        candidates = (
            await s.scalars(
                select(VpnAccount.id)
                .where(overdue, VpnAccount.panel_id.is_not(None), not_just_read)
                .order_by(VpnAccount.last_synced_at.asc().nulls_first())
                .limit(EXPIRY_LIVE_BATCH)
            )
        ).all()
        for account_id in candidates:
            try:
                await reconcile.reconcile_account(s, account_id)  # applies the panel's status; notices fire from sync.apply_remote
            except Exception:
                await s.rollback()
                log.warning("expiry: live read failed account=%s", account_id, exc_info=True)
        return len(candidates)


async def near_expiry_job(ctx=None):
    """Warn customers whose subscription is about to end.

    Mediator rule: the SOLD expiry only nominates candidates. For an account on a panel the warning is sent only after a live read
    says the panel agrees: not ``on_hold`` (its clock has not started), and the panel's own expiry is inside the window (a renewal
    done on the panel pushes it out). A panel that does not answer sends nothing and leaves the flag unset, so the next run tries
    again. An account without a panel has no other source, so its sold expiry is used as before.
    """
    async with session_factory()() as s:
        hours = int(await settings_store.get(s, "vpn.near_expiry_hours") or 48)
        now, end = utcnow(), utcnow() + dt.timedelta(hours=hours)
        accounts = (
            await s.scalars(
                select(VpnAccount).where(
                    VpnAccount.status == "active",
                    VpnAccount.near_expiry_notified.is_(False),
                    VpnAccount.sold_expires_at > now,
                    VpnAccount.sold_expires_at <= end,
                )
            )
        ).all()
        on_panel = [a for a in accounts if a.panel_id]
        readings = await live.read(s, on_panel[: live.MAX_ACCOUNTS]) if on_panel else {}
        for a in accounts:
            if a.panel_id:
                reading = readings.get(a.id)
                if reading is None or reading.remote_status == "on_hold":
                    continue  # no verdict (panel silent / clock not started): ask again next run, flag untouched
                panel_expiry = reading.expires_at
                if panel_expiry is not None:
                    if panel_expiry.tzinfo is None:
                        panel_expiry = panel_expiry.replace(tzinfo=dt.UTC)
                    if not (now < panel_expiry <= end):
                        continue  # renewed (or already over) on the panel: this warning would be wrong
            a.near_expiry_notified = True  # reset by a renewal (notices.reset_for_renewal), so the NEXT period warns again
            await notices.near_expiry(s, a)
        await s.commit()


async def reconciliation_job(ctx=None):
    """Hourly: reconcile v2 (PG-04). One batched read per panel; accounts that waited longest go first; issues open, refresh
    and close themselves. A failing panel never stops the others."""
    done = 0
    async with session_factory()() as s:
        panel_ids = (await s.scalars(select(Panel.id).where(Panel.is_enabled.is_(True)))).all()
    for panel_id in panel_ids:
        async with session_factory()() as s:
            try:
                panel = await s.get(Panel, panel_id)
                if panel is None:
                    continue
                result = await reconcile.reconcile_panel(s, panel)
                done += result.checked
                if result.unreachable:
                    log.warning("reconcile: panel=%s unreachable: %s", panel_id, "; ".join(result.errors))
            except Exception:
                await s.rollback()
                log.warning("reconcile failed panel=%s", panel_id, exc_info=True)
    return done


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
    from melorin.channels.telegram import web as telegram_web

    async with session_factory()() as s:
        removed = await telegram_web.purge_old(s)
        log.info("telegram web login sessions removed=%s", removed)
        return removed


async def identity_auto_link_job(ctx=None):
    """Safety net for identity-link conflicts (docs/21): settle every open review that became safe to merge by itself
    (an empty shell stayed empty). Two accounts that both hold records are left for an admin."""
    from melorin.modules.identity import auto_link

    async with session_factory()() as s:
        settled = await auto_link.sweep(s)
        if settled:
            log.info("identity conflicts settled automatically=%s", settled)
        return settled


async def reseller_auto_verify_job(ctx=None):
    """Reseller applications verify themselves (docs/21): re-check the bot and the domain proof of every pending
    application whose retry is due. Back-off lives on the row, so a restart or a second worker never double-runs it."""
    from melorin.modules.reseller import auto_verify

    async with session_factory()() as s:
        done = await auto_verify.sweep(s)
        if done:
            log.info("reseller applications auto-verified rounds=%s", done)
        return done


async def reseller_identity_recheck_job(ctx=None):
    """Approved resellers keep proving who they are (docs/21): re-check domain proof and bot token of every store whose
    check is due; repeated failure alerts admins (and suspends the store when RESELLER_RECHECK_SUSPEND is on)."""
    from melorin.modules.reseller import recheck

    async with session_factory()() as s:
        done = await recheck.sweep(s)
        if done:
            log.info("reseller identities re-checked=%s", done)
        return done


async def bank_sms_reconcile_job(ctx=None):
    """Safety net for card-to-card auto verification: pair open deposit SMS with receipts uploaded later or whose
    inline match failed. Idempotent; the wallet credit is protected by the ledger idempotency key."""
    from melorin.kernel.models.payments import BankSmsSource
    from melorin.kernel.models.stores import Store
    from melorin.modules.payments import bank_sms

    total = 0
    async with session_factory()() as s:
        ids = (
            await s.scalars(select(BankSmsSource.store_id).where(BankSmsSource.is_enabled.is_(True), BankSmsSource.auto_verify.is_(True)))
        ).all()
        for store_id in ids:
            try:
                store = await s.get(Store, store_id)
                if store:
                    total += (await bank_sms.reconcile_store(s, store))["matched"]
            except Exception:
                await s.rollback()
                log.warning("bank sms reconcile failed store=%s", store_id, exc_info=True)
    return total


async def receipt_grace_job(ctx=None):
    """Time-boxed manual review: credit provisionally (and flag for fast review) every card-to-card receipt that
    waited longer than the store's grace minutes. Runs every minute; idempotent."""
    from melorin.modules.payments import provisional

    async with session_factory()() as s:
        try:
            n = await provisional.sweep(s)
        except Exception:
            await s.rollback()
            log.warning("receipt grace sweep failed", exc_info=True)
            return 0
        if n:
            log.info("receipt grace: provisional credits=%s", n)
        return n


async def panel_admin_sync_job(ctx=None):
    """Every minute: a new reseller / a new PasarGuard panel / an existing reseller meeting a new panel gets its Operator admin."""
    from melorin.modules.vpn import panel_admins

    async with session_factory()() as s:
        return await panel_admins.sync_all(s)


async def panel_event_job(ctx=None):
    """Every 10 seconds: process the PasarGuard events the endpoint stored (PG-03). Coalesced per user, leased, safe to run twice.

    This is NOT a second way of receiving events (audit T07): nothing here asks the panel what happened. There is one path in, the webhook
    (``ingest`` stores each event once by ``(panel_id, dedup_key)``), and one consumer, ``run_pending``; the webhook calls it right away for
    latency and this job sweeps what is left. Events the panel never delivered are caught by the hourly reconcile, not by polling."""
    stats = await panel_events.run_pending()
    return stats.claimed


async def panel_event_purge_job(ctx=None):
    """Daily: drop finished panel events older than the retention window (30 days)."""
    async with session_factory()() as s:
        removed = await panel_events.purge(s)
    log.info("panel events retention removed=%s", removed)
    return removed


async def bulk_operation_job(ctx=None):
    """Every 15 seconds: run ONE confirmed bulk operation for up to ~40 s (PG-11). Leased per panel, chunked, resumable: a crash or a
    second worker can never apply an item twice (absolute targets + ledger)."""
    from melorin.modules.vpn import bulk

    op = await bulk.run_next(session_factory(), budget_seconds=40.0)
    return op.status if op else None


async def store_governance_job(ctx=None):
    """Every 15 minutes: read each store admin's usage / status / user count from its panel (PG-12)."""
    from melorin.modules.vpn import governance

    done = 0
    async with session_factory()() as s:
        panels = (await s.scalars(select(Panel).where(Panel.is_enabled.is_(True), Panel.kind == "pasarguard"))).all()
        for p in panels:
            try:
                done += (await governance.sync_usage(s, p)).updated
            except Exception:
                log.warning("store governance sync failed panel=%s", p.id, exc_info=True)
        await s.commit()
    return done
