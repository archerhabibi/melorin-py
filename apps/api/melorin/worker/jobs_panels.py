"""Panel jobs: one read cycle (health/metrics/capacity), drift, admin sync, provider events, bulk runs, governance, reconciliation."""

import functools
import logging

from sqlalchemy import select

from melorin.core.db import session_factory, utcnow
from melorin.modules.eventcenter import rules as event_center_rules
from melorin.modules.vpn import capacity, health, panel_events, reconcile
from melorin.modules.panel_integrations import capabilities
from melorin.kernel.models.vpn import Panel
from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter
from melorin.worker.wrap import item_failed, tracked_job

_close_strict = functools.partial(close_adapter, strict=True)  # worker jobs keep raising on close failure
log = logging.getLogger("melorin.jobs")




@tracked_job
async def panel_health_job(ctx=None):
    """Every 2 minutes: ONE read cycle per panel: health in two layers (PG-01) plus the metrics snapshot (PG-14) on the same adapter. The panel must answer AND have a connected node; a failing node
    alone makes the panel ``degraded`` (still selling), no connected node makes it ``unhealthy`` (leaves server selection)."""
    async with session_factory()() as s:
        from melorin.modules.panelops import panel_metrics
        from melorin.modules.panel_integrations.adapters.registry import build_adapter

        panels = (await s.scalars(select(Panel).where(Panel.is_enabled.is_(True)))).all()
        for p in panels:
            adapter = None
            result = health.HealthResult(health.UNHEALTHY, "unknown")
            capacity_changes: list = []
            try:
                adapter = build_adapter(p)
                result = await health.check_panel(s, p, adapter)
                # One read cycle per panel: the metrics snapshot reuses this adapter/login (never raises).
                await panel_metrics.snapshot_panel(p, adapter)
                if result.status != health.UNHEALTHY and capabilities.is_stale(
                    p
                ):  # hourly: permissions change when the panel role is edited
                    try:
                        await capabilities.refresh(p, adapter)
                    except Exception:  # a probe problem must never flip the panel to unhealthy
                        item_failed("panel_health_job")
                        log.warning("panel capability refresh failed panel=%s", p.id, exc_info=True)
                if result.status != health.UNHEALTHY:  # PG-08: layer 3, the destinations' real group/host/node state and fill level
                    try:
                        capacity_changes = await capacity.refresh_panel(s, p, adapter)
                    except Exception:  # never let a capacity problem change the panel's verdict
                        item_failed("panel_health_job")
                        log.warning("panel capacity refresh failed panel=%s", p.id, exc_info=True)
            except Exception as exc:
                result = health.HealthResult(
                    health.UNHEALTHY, str(exc)[:500], {"layer": 1, "sellable": False, "checked_at": utcnow().isoformat()}
                )
            finally:
                if adapter:
                    try:
                        await close_adapter(adapter, strict=True)
                    except Exception:
                        log.exception("panel adapter close failed panel=%s", p.id)
            previous = health.apply(p, result)
            await event_center_rules.notify_panel_health(s, p, previous)
            await event_center_rules.notify_panel_nodes(s, p, result.node_changes)
            await event_center_rules.notify_server_capacity(s, p, capacity_changes)
        await s.commit()



@tracked_job
async def panel_metrics_job(ctx=None):
    """Every 2 minutes: one live reading per panel (latency, resources, users, online) for the /metrics gauges (PG-14)."""
    from melorin.modules.panelops import panel_metrics

    async with session_factory()() as s:
        done = await panel_metrics.run_snapshots(s, close_adapter=_close_strict)
        await s.commit()
    return done



@tracked_job
async def panel_settings_drift_job(ctx=None):
    """Hourly: compare each PasarGuard panel's settings with what Melorin needs. READ-ONLY: it reports, an admin decides (PG-15)."""
    from melorin.modules.panelops import settings_drift

    async with session_factory()() as s:
        done = await settings_drift.run_all(s, close_adapter=_close_strict)
        await s.commit()
    return done



@tracked_job
async def panel_admin_sync_job(ctx=None):
    """Every 15 minutes (retry + safety net): panel create and reseller create already plan and push the Operator admin on the spot."""
    from melorin.modules.panelops import panel_admins

    async with session_factory()() as s:
        return await panel_admins.sync_all(s)



@tracked_job
async def panel_event_job(ctx=None):
    """Every 10 seconds: process the PasarGuard events the endpoint stored (PG-03). Coalesced per user, leased, safe to run twice.

    This is NOT a second way of receiving events (audit T07): nothing here asks the panel what happened. There is one path in, the webhook
    (``ingest`` stores each event once by ``(panel_id, dedup_key)``), and one consumer, ``run_pending``; the webhook calls it right away for
    latency and this job sweeps what is left. Events the panel never delivered are caught by the hourly reconcile, not by polling."""
    stats = await panel_events.run_pending()
    return stats.claimed



@tracked_job
async def panel_event_purge_job(ctx=None):
    """Daily: drop finished panel events older than the retention window (30 days)."""
    async with session_factory()() as s:
        removed = await panel_events.purge(s)
    log.info("panel events retention removed=%s", removed)
    return removed



@tracked_job
async def bulk_operation_job(ctx=None):
    """Every 15 seconds: run ONE confirmed bulk operation for up to ~40 s (PG-11). Leased per panel, chunked, resumable: a crash or a
    second worker can never apply an item twice (absolute targets + ledger)."""
    from melorin.modules.panelops import bulk

    op = await bulk.run_next(session_factory(), budget_seconds=40.0)
    return op.status if op else None



@tracked_job
async def store_governance_job(ctx=None):
    """Every 15 minutes: read each store admin's usage / status / user count from its panel (PG-12)."""
    from melorin.modules.panelops import governance

    done = 0
    async with session_factory()() as s:
        panels = (await s.scalars(select(Panel).where(Panel.is_enabled.is_(True), Panel.kind == "pasarguard"))).all()
        for p in panels:
            try:
                done += (await governance.sync_usage(s, p)).updated
            except Exception:
                item_failed("store_governance_job")
                log.warning("store governance sync failed panel=%s", p.id, exc_info=True)
        await s.commit()
    return done



@tracked_job
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
                item_failed("reconciliation_job")
                log.warning("reconcile failed panel=%s", panel_id, exc_info=True)
    return done


