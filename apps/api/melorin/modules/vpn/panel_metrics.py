"""Panel metrics and alerts (PG-14): what an operator needs on a dashboard to see a panel going wrong BEFORE customers do.

Two halves, because a Prometheus scrape must never wait for a remote panel:

* ``snapshot_panel`` / ``run_snapshots`` (worker, every 2 minutes) take ONE live reading per panel - API latency, resources, users by
  status, online users - and store it on ``panels.metrics_snapshot``.
* ``collect`` (the API, on every ``/metrics`` scrape) renders gauges from the database only: that snapshot, the node rows, reconcile
  issues, capacity, webhook silence and panel-backup age. It also feeds ``set_alert`` so the admin UI and Prometheus rules agree.

Series are labelled by panel *name* (and server name). A gauge with no data (e.g. a credential that cannot read nodes) is simply not
emitted: absence means "unknown", never a fake zero. Nothing here writes to a panel."""

from __future__ import annotations

import datetime as dt
import logging
import os
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.core.metrics import clear_gauges, set_alert, set_gauge
from melorin.kernel.models.system import BackupRun
from melorin.kernel.models.vpn import Panel, PanelNode, ReconciliationIssue, Server, VpnAccount
from melorin.modules.vpn import capabilities as panel_caps
from melorin.modules.vpn import capacity
from melorin.modules.vpn.adapters.base import PanelError, supports

log = logging.getLogger("melorin.vpn.panel_metrics")

SNAPSHOT_FRESH = dt.timedelta(minutes=15)  # older than this and the numbers are flagged stale (the job died or the panel is down)
RECONCILE_LAG_MAX = dt.timedelta(hours=3)  # reconcile runs hourly; three missed rounds is an incident
PANEL_BACKUP_MAX_AGE = dt.timedelta(hours=36)
CAPACITY_ALERT_RATIO = 0.95
NODE_STATES = ("connected", "connecting", "disabled", "error")  # ``limited`` / ``unknown`` count as error
USER_STATES = ("active", "on_hold", "disabled", "expired", "limited")
ISSUE_KINDS = ("missing_on_panel", "panel_unreachable", "owner_mismatch", "limits_mismatch")
LOAD_ACCOUNT_STATUSES = ("active", "suspended", "limited", "expired")  # accounts reconcile keeps comparing with the panel

GAUGES = (
    "melorin_panel_up",
    "melorin_panel_nodes",
    "melorin_panel_users",
    "melorin_panel_online_users",
    "melorin_panel_cpu_ratio",
    "melorin_panel_mem_ratio",
    "melorin_panel_disk_ratio",
    "melorin_panel_api_latency_seconds",
    "melorin_panel_snapshot_age_seconds",
    "melorin_panel_webhook_lag_seconds",
    "melorin_panel_settings_drift",
    "melorin_reconcile_open_issues",
    "melorin_reconcile_lag_seconds",
    "melorin_server_capacity_ratio",
)


def _aware(d: dt.datetime | None) -> dt.datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)


def _ratio(used, total) -> float | None:
    try:
        used, total = float(used), float(total)
    except (TypeError, ValueError):
        return None
    if total <= 0 or used < 0:
        return None
    return round(min(used / total, 1.0), 4)


def _num(value) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


# ------------------------------------------------------------------------------------------------------------ live reading (worker)
def parse_system(stats: dict | None) -> dict:
    """PasarGuard ``GET /api/system`` -> the few numbers we keep. Unknown / malformed fields are left out, never guessed."""
    s = stats if isinstance(stats, dict) else {}
    out: dict = {}
    users = {}
    for state in USER_STATES:
        n = _num(s.get(f"{state}_users"))
        if n is not None:
            users[state] = int(n)
    total = _num(s.get("total_user"))
    if users or total is not None:
        out["users"] = users
        if total is not None:
            out["users_total"] = int(total)
    online = _num(s.get("online_users"))
    if online is not None:
        out["online_users"] = int(online)
    cpu = _num(s.get("cpu_usage"))  # percent, 0..100
    if cpu is not None and cpu >= 0:
        out["cpu_ratio"] = round(min(cpu / 100.0, 1.0), 4)
    mem = _ratio(s.get("mem_used"), s.get("mem_total"))
    if mem is not None:
        out["mem_ratio"] = mem
    disk = _ratio(s.get("disk_used"), s.get("disk_total"))
    if disk is not None:
        out["disk_ratio"] = disk
    return out


async def snapshot_panel(panel: Panel, adapter, *, now: dt.datetime | None = None) -> dict:
    """One live reading of ``panel`` stored on the row (the caller commits). Never raises: a failure is recorded in the snapshot."""
    now = now or utcnow()
    snap: dict = {"taken_at": now.isoformat(), "up": False}
    started = time.perf_counter()
    try:
        snap["up"] = bool(await adapter.health_check())
    except PanelError as exc:
        snap["error"] = exc.message[:200]
    except Exception as exc:  # an adapter bug must not stop the other panels' readings
        snap["error"] = f"{exc.__class__.__name__}: {str(exc)[:150]}"
    snap["latency_seconds"] = round(time.perf_counter() - started, 4)
    if snap["up"] and panel_caps.capabilities_of(panel).has("node_insight") and supports(adapter, "node_insight"):
        try:
            snap.update(parse_system(await adapter.get_system_stats()))
        except PanelError as exc:  # the credential may not read ``system``: the panel is still up
            snap["insight_error"] = exc.message[:200]
        except Exception as exc:
            snap["insight_error"] = f"{exc.__class__.__name__}: {str(exc)[:150]}"
    panel.metrics_snapshot, panel.metrics_snapshot_at = snap, now
    return snap


async def run_snapshots(session: AsyncSession, *, close_adapter) -> int:
    """Worker entry: a snapshot for every enabled panel. One bad panel never blocks the others."""
    from melorin.modules.vpn.adapters.registry import build_adapter

    done = 0
    for panel in (await session.scalars(select(Panel).where(Panel.is_enabled.is_(True)))).all():
        adapter = None
        try:
            adapter = build_adapter(panel)
            await snapshot_panel(panel, adapter)
            done += 1
        except Exception:
            log.warning("panel metrics snapshot failed panel=%s", panel.id, exc_info=True)
        finally:
            if adapter is not None:
                try:
                    await close_adapter(adapter)
                except Exception:
                    log.warning("panel metrics: adapter close failed panel=%s", panel.id, exc_info=True)
    return done


# ------------------------------------------------------------------------------------------------------------ scrape time (API)
def panel_backup_configured() -> bool:
    return bool(os.getenv("MELORIN_PANEL_BACKUP_DATABASE_URL") or os.getenv("MELORIN_PANEL_BACKUP_PATHS"))


async def _backup_age(session: AsyncSession, target: str, now: dt.datetime) -> float | None:
    last = await session.scalar(select(func.max(BackupRun.created_at)).where(BackupRun.status == "succeeded", BackupRun.target == target))
    last = _aware(last)
    return None if last is None else max((now - last).total_seconds(), 0.0)


def _node_counts(rows) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for panel_id, status, n in rows:
        bucket = out.setdefault(str(panel_id), dict.fromkeys(NODE_STATES, 0))
        bucket[status if status in NODE_STATES else "error"] += int(n)
    return out


async def collect(session: AsyncSession, now: dt.datetime | None = None) -> dict[str, float]:
    """Refresh the panel gauges and alerts from the database; returns ``{"name{labels}": value}`` for tests."""
    now = now or utcnow()
    clear_gauges(*GAUGES)
    seen: dict[str, float] = {}

    def put(name: str, value: float, **labels: str) -> None:
        set_gauge(name, value, **labels)
        seen[name + ("{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}" if labels else "")] = value

    panels = (await session.scalars(select(Panel).where(Panel.is_enabled.is_(True)).order_by(Panel.name))).all()
    node_rows = (
        await session.execute(
            select(PanelNode.panel_id, PanelNode.status, func.count())
            .where(PanelNode.removed_at.is_(None))
            .group_by(PanelNode.panel_id, PanelNode.status)
        )
    ).all()
    nodes = _node_counts(node_rows)

    node_down: list[str] = []
    degraded: list[str] = []
    drifting: list[str] = []
    stale: list[str] = []
    for p in panels:
        name = p.name
        if p.health_status in ("healthy", "degraded", "unhealthy"):
            set_gauge("melorin_panel_up", 0.0 if p.health_status == "unhealthy" else 1.0, panel=name)
            seen[f'melorin_panel_up{{panel="{name}"}}'] = 0.0 if p.health_status == "unhealthy" else 1.0
        if p.health_status == "degraded":
            degraded.append(name)
        counts = nodes.get(str(p.id))
        if counts is not None:
            for state in NODE_STATES:
                put("melorin_panel_nodes", float(counts[state]), panel=name, status=state)
            if counts["error"] and counts["connected"] == 0:
                node_down.append(name)
        snap = p.metrics_snapshot if isinstance(p.metrics_snapshot, dict) else None
        taken = _aware(p.metrics_snapshot_at)
        if snap is not None and taken is not None:
            age = max((now - taken).total_seconds(), 0.0)
            put("melorin_panel_snapshot_age_seconds", age, panel=name)
            if age > SNAPSHOT_FRESH.total_seconds():
                stale.append(name)
            latency = _num(snap.get("latency_seconds"))
            if latency is not None:
                put("melorin_panel_api_latency_seconds", latency, panel=name)
            for state, n in (snap.get("users") or {}).items():
                if state in USER_STATES:
                    put("melorin_panel_users", float(n), panel=name, status=state)
            if _num(snap.get("online_users")) is not None:
                put("melorin_panel_online_users", float(snap["online_users"]), panel=name)
            for key, metric in (
                ("cpu_ratio", "melorin_panel_cpu_ratio"),
                ("mem_ratio", "melorin_panel_mem_ratio"),
                ("disk_ratio", "melorin_panel_disk_ratio"),
            ):
                if _num(snap.get(key)) is not None:
                    put(metric, float(snap[key]), panel=name)
        if p.webhook_connected_at is not None:
            quiet_since = _aware(p.webhook_last_at) or _aware(p.webhook_connected_at)
            put("melorin_panel_webhook_lag_seconds", max((now - quiet_since).total_seconds(), 0.0), panel=name)
        drift = p.settings_drift if isinstance(p.settings_drift, dict) else None
        if drift is not None:
            n = int(drift.get("drifting") or 0)
            put("melorin_panel_settings_drift", float(n), panel=name)
            if n:
                drifting.append(name)

    # Reconcile: open issues per kind (always all kinds, so a cleared issue drops to 0 instead of vanishing) and the oldest sync.
    issue_rows = dict(
        (
            await session.execute(
                select(ReconciliationIssue.kind, func.count())
                .where(ReconciliationIssue.status == "open")
                .group_by(ReconciliationIssue.kind)
            )
        ).all()
    )
    for kind in sorted(set(ISSUE_KINDS) | set(issue_rows)):
        put("melorin_reconcile_open_issues", float(issue_rows.get(kind, 0)), kind=kind)
    oldest = await session.scalar(
        select(func.min(func.coalesce(VpnAccount.last_synced_at, VpnAccount.created_at))).where(
            VpnAccount.status.in_(LOAD_ACCOUNT_STATUSES), VpnAccount.panel_id.is_not(None), VpnAccount.archived_at.is_(None)
        )
    )
    lag = max((now - _aware(oldest)).total_seconds(), 0.0) if oldest is not None else 0.0
    put("melorin_reconcile_lag_seconds", lag)

    # Capacity per destination (the same numbers the admin sees: Melorin's count, or the panel's when the server is panel-sourced).
    servers = (await session.scalars(select(Server).where(Server.is_enabled.is_(True)).order_by(Server.name))).all()
    counts_by_server = await capacity.active_counts(session, [s.id for s in servers])
    full: list[str] = []
    for s in servers:
        if not s.capacity:
            continue
        view = capacity.capacity_view(s, counts_by_server.get(s.id, 0))
        ratio = round(view["used"] / int(s.capacity), 4)
        put("melorin_server_capacity_ratio", ratio, server=s.name)
        if ratio >= CAPACITY_ALERT_RATIO:
            full.append(s.name)

    # Panel backup age (PG-16): reported only when panel backup is configured or has ever run, otherwise it is "not in use", not "stale".
    panel_age = await _backup_age(session, "panel", now)
    backup_in_use = panel_backup_configured() or panel_age is not None
    if backup_in_use:
        value = panel_age if panel_age is not None else 10**9
        set_gauge("melorin_backup_age_seconds", value, target="panel")
        seen['melorin_backup_age_seconds{target="panel"}'] = value

    def alert(name: str, firing: list[str] | bool, summary: str, severity: str = "warning") -> None:
        is_firing = bool(firing)
        set_alert(name, is_firing, summary=summary, severity=severity, details=", ".join(firing)[:300] if isinstance(firing, list) else "")

    alert("MelorinPanelNodeDown", node_down, "A panel has failing nodes and none connected: nobody can be served", "critical")
    alert("MelorinPanelDegraded", degraded, "A panel has failing nodes but still serves customers")
    alert("MelorinReconcileLagHigh", lag > RECONCILE_LAG_MAX.total_seconds(), "Panel reconcile is not keeping up with the accounts")
    alert("MelorinCapacityHigh", full, "A server is 95% full or more")
    alert("MelorinPanelMetricsStale", stale, "Panel readings are older than 15 minutes (panel down or metrics job stopped)")
    alert("MelorinPanelSettingsDrift", drifting, "A panel's settings differ from what Melorin needs")
    alert(
        "MelorinPanelBackupStale",
        backup_in_use and (panel_age is None or panel_age > PANEL_BACKUP_MAX_AGE.total_seconds()),
        "No successful panel backup within 36 hours",
        "critical",
    )
    return seen
