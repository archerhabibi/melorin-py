"""Panel operations console (PG-07): what the admin needs to see why a node fails and to fix it without opening PasarGuard.

Read side (``overview``): the panel's resources, user counts and live node stats, merged with Melorin's own node rows (error text and a fix
hint). Each section fails on its own, so a credential that cannot read ``system`` still shows the nodes.

Write side (``node_reconnect``, ``node_sync``, ``core_restart``, ``toggle``): the admin confirms (a reason is required, a core restart also
needs the core's name typed), the call is audited, and Melorin refreshes its node view straight away. Every call is absolute or idempotent.
``toggle`` refuses to disable the last connected node unless ``force`` is set: that single click would stop the whole panel."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.vpn import Panel, PanelNode
from melorin.modules.vpn import health
from melorin.modules.panel_integrations import capabilities as panel_caps
from melorin.modules.panel_integrations.adapters.base import PanelError, supports
from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter
from melorin.modules.panel_integrations.adapters.registry import build_adapter

log = logging.getLogger("melorin.vpn.ops_console")

FAMILIES = ("nodes", "hosts", "groups")
MAX_IDS = 200
SYSTEM_KEYS = (
    "version", "cpu_cores", "cpu_usage", "mem_total", "mem_used", "total_user", "online_users", "active_users", "on_hold_users",
    "disabled_users", "expired_users", "limited_users", "incoming_bandwidth", "outgoing_bandwidth", "incoming_bandwidth_speed",
    "outgoing_bandwidth_speed",
)  # fmt: skip
REALTIME_KEYS = ("cpu_usage", "cpu_cores", "mem_used", "mem_total", "incoming_bandwidth_speed", "outgoing_bandwidth_speed", "uptime")


def _pick(row: dict | None, keys: tuple[str, ...]) -> dict | None:
    if not isinstance(row, dict):
        return None
    return {k: row[k] for k in keys if k in row and isinstance(row[k], int | float | str | bool | type(None))}


def _scalars(row: dict | None) -> dict:
    return {k: v for k, v in (row or {}).items() if isinstance(v, int | float | str | bool)}


def reason_required(reason: str | None) -> str:
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise AppError("REASON_REQUIRED", "برای این عملیات دلیل را بنویسید.", 400)
    return reason[:300]


async def _panel(session: AsyncSession, panel_id: uuid.UUID) -> Panel:
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    if panel.kind != "pasarguard":
        raise AppError("OPS_NOT_SUPPORTED", "کنسول عملیات فعلاً فقط برای پنل پاسارگارد است.", 409)
    return panel


def _need(adapter, capability: str) -> None:
    if not supports(adapter, capability):
        raise AppError("CAPABILITY_MISSING", "اتصال این پنل دسترسی لازم برای این عملیات را ندارد.", 409, {"capability": capability})


def _panel_error(exc: PanelError) -> AppError:
    return AppError("PANEL_ERROR", f"پنل درخواست را نپذیرفت: {exc.message[:200]}", 502)


# ------------------------------------------------------------------------------------------------------------------ read
async def overview(session: AsyncSession, panel_id: uuid.UUID) -> dict:
    panel = await _panel(session, panel_id)
    caps = panel_caps.capabilities_out(panel)
    rows = (
        await session.scalars(
            select(PanelNode).where(PanelNode.panel_id == panel.id, PanelNode.removed_at.is_(None)).order_by(PanelNode.name)
        )
    ).all()
    errors: dict[str, str] = {}
    system = resources = None
    realtime: dict[int, dict | None] = {}
    adapter = None
    try:
        adapter = build_adapter(panel)
        if supports(adapter, "node_insight"):
            for name, call in (
                ("system", adapter.get_system_stats),
                ("resources", adapter.get_system_resources),
                ("realtime", adapter.get_nodes_realtime),
            ):
                try:
                    data = await call()
                except PanelError as exc:
                    errors[name] = exc.message[:200]
                    continue
                if name == "system":
                    system = _pick(data, SYSTEM_KEYS)
                elif name == "resources":
                    resources = _scalars(data)
                else:
                    realtime = data
        else:
            errors["insight"] = "این اتصال دسترسی خواندن آمار پنل (system.read و nodes.stats) را ندارد."
    except AppError as exc:
        errors["connection"] = exc.message
    finally:
        if adapter is not None:
            await close_adapter(adapter)
    nodes = [
        {
            "remote_id": r.remote_id,
            "name": r.name,
            "status": r.status,
            "message": r.message,
            "hint": health.node_error_hint(r.message) if r.status in health.NODE_BAD else None,
            "xray_version": r.xray_version,
            "usage_coefficient": r.usage_coefficient,
            "last_seen_at": r.last_seen_at,
            "realtime": _pick(realtime.get(r.remote_id), REALTIME_KEYS),
        }
        for r in rows
    ]
    flags = caps.get("flags", {})
    return {
        "panel_id": panel.id,
        "health_status": panel.health_status,
        "can": {
            "reconnect": bool(flags.get("node_control")),
            "infra": bool(flags.get("infra_control")),
            "insight": bool(flags.get("node_insight")),
        },
        "system": system,
        "resources": resources,
        "nodes": nodes,
        "errors": errors,
    }


async def list_infra(session: AsyncSession, panel_id: uuid.UUID) -> dict:
    """Groups and hosts with their enabled state (what ``toggle`` acts on), plus the cores (what ``core_restart`` acts on)."""
    panel = await _panel(session, panel_id)
    adapter = build_adapter(panel)
    try:
        out: dict = {"groups": [], "hosts": [], "cores": []}
        if supports(adapter, "capacity_ops"):
            try:
                out["groups"] = [
                    {"id": g.get("id"), "name": g.get("name"), "disabled": bool(g.get("is_disabled")), "total_users": g.get("total_users")}
                    for g in await adapter.list_groups_full()
                ]
                out["hosts"] = [
                    {
                        "id": h.get("id"),
                        "remark": h.get("remark"),
                        "inbound_tag": h.get("inbound_tag"),
                        "disabled": bool(h.get("is_disabled")),
                    }
                    for h in await adapter.list_hosts()
                ]
            except PanelError as exc:
                raise _panel_error(exc) from exc
        if supports(adapter, "infra_control"):
            try:
                out["cores"] = [{"id": c.get("id"), "name": c.get("name")} for c in await adapter.list_cores()]
            except PanelError as exc:
                raise _panel_error(exc) from exc
        return out
    finally:
        await close_adapter(adapter)


# ------------------------------------------------------------------------------------------------------------------ write
async def _refresh(session: AsyncSession, panel: Panel, adapter) -> None:
    """Re-read nodes right after an action so the admin sees the effect (best effort: the periodic job would do it anyway)."""
    try:
        result = await health.check_panel(session, panel, adapter)
        health.apply(panel, result)
    except Exception:
        log.warning("ops console: node refresh failed panel=%s", panel.id, exc_info=True)


def _audit(session, panel: Panel, admin_id, action: str, data: dict) -> None:
    audit.record(session, f"panel.ops.{action}", actor_id=admin_id, actor_type="admin", entity_type="panel", entity_id=panel.id, data=data)


async def node_action(session: AsyncSession, panel_id: uuid.UUID, node_id: int, action: str, *, admin_id, reason: str | None) -> dict:
    """``reconnect`` (nodes.reconnect) or ``sync`` (re-send configuration; no user is dropped)."""
    if action not in ("reconnect", "sync"):
        raise AppError("BAD_ACTION", "عملیات نامعتبر است.", 400)
    reason = reason_required(reason)
    panel = await _panel(session, panel_id)
    node = await session.scalar(
        select(PanelNode).where(PanelNode.panel_id == panel.id, PanelNode.remote_id == int(node_id), PanelNode.removed_at.is_(None))
    )
    if node is None:
        raise NotFound("نود")
    adapter = build_adapter(panel)
    try:
        _need(adapter, "node_control" if action == "reconnect" else "infra_control")
        try:
            await (adapter.reconnect_node(int(node_id)) if action == "reconnect" else adapter.sync_node(int(node_id)))
        except PanelError as exc:
            raise _panel_error(exc) from exc
        await _refresh(session, panel, adapter)
    finally:
        await close_adapter(adapter)
    _audit(session, panel, admin_id, f"node_{action}", {"node": node.name, "remote_id": node.remote_id, "reason": reason})
    await session.commit()
    return {"ok": True, "action": action, "node": node.name}


async def core_restart(
    session: AsyncSession, panel_id: uuid.UUID, core_id: int, *, admin_id, reason: str | None, confirm_name: str | None
) -> dict:
    """Restarting a core briefly drops every connection through it: the admin must type the core's exact name."""
    reason = reason_required(reason)
    panel = await _panel(session, panel_id)
    adapter = build_adapter(panel)
    try:
        _need(adapter, "infra_control")
        try:
            cores = await adapter.list_cores()
        except PanelError as exc:
            raise _panel_error(exc) from exc
        core = next((c for c in cores if c.get("id") == int(core_id)), None)
        if core is None:
            raise NotFound("هسته")
        if (confirm_name or "").strip() != str(core.get("name") or ""):
            raise AppError("CONFIRM_NAME_MISMATCH", "نام هسته را دقیقاً تایپ کنید تا ری‌استارت تأیید شود.", 409)
        try:
            await adapter.restart_core(int(core_id))
        except PanelError as exc:
            raise _panel_error(exc) from exc
    finally:
        await close_adapter(adapter)
    _audit(session, panel, admin_id, "core_restart", {"core": core.get("name"), "core_id": int(core_id), "reason": reason})
    await session.commit()
    return {"ok": True, "core": core.get("name")}


async def toggle(
    session: AsyncSession,
    panel_id: uuid.UUID,
    family: str,
    ids: list[int],
    disabled: bool,
    *,
    admin_id,
    reason: str | None,
    force: bool = False,
) -> dict:
    """Enable/disable nodes, hosts or groups. Absolute (``disabled=true|false``), so repeating it is harmless."""
    if family not in FAMILIES:
        raise AppError("BAD_FAMILY", "نوع منبع نامعتبر است.", 400)
    reason = reason_required(reason)
    ids = sorted({int(i) for i in ids if int(i) > 0})
    if not ids or len(ids) > MAX_IDS:
        raise AppError("BAD_IDS", f"بین ۱ تا {MAX_IDS} شناسه لازم است.", 400)
    panel = await _panel(session, panel_id)
    if family == "nodes" and disabled and not force:
        connected = (
            await session.scalars(
                select(PanelNode.remote_id).where(
                    PanelNode.panel_id == panel.id, PanelNode.removed_at.is_(None), PanelNode.status == health.NODE_OK
                )
            )
        ).all()
        if connected and not (set(connected) - set(ids)):
            raise AppError(
                "LAST_NODE", "با این کار هیچ نود متصلی نمی‌ماند و پنل از فروش خارج می‌شود. فقط با تأیید صریح (force) انجام می‌شود.", 409
            )
    adapter = build_adapter(panel)
    try:
        _need(adapter, "infra_control")
        call = {"nodes": adapter.set_nodes_disabled, "hosts": adapter.set_hosts_disabled, "groups": adapter.set_groups_disabled}[family]
        try:
            await call(ids, disabled)
        except PanelError as exc:
            raise _panel_error(exc) from exc
        if family == "nodes":
            await _refresh(session, panel, adapter)
    finally:
        await close_adapter(adapter)
    _audit(session, panel, admin_id, f"{family}_{'disable' if disabled else 'enable'}", {"ids": ids, "reason": reason, "force": force})
    await session.commit()
    return {"ok": True, "family": family, "disabled": disabled, "count": len(ids)}
