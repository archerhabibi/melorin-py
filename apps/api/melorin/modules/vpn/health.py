"""Real panel health (PG-01): the panel answering is not enough, its NODES must be able to serve customers.

Layers:  1. the panel API answers (``health_check``);  2. its nodes (``NodeOps``): connected / error / disabled counts and reasons.
(Layer 3, group -> host -> node reachability per destination, belongs to the capacity work PG-08.)

States:
  ``healthy``    layer 1 ok and every enabled node connected (or the node data is not available to this credential)
  ``degraded``   some enabled node is failing but at least one is connected: customers can still be served
  ``unhealthy``  the panel does not answer, or NO enabled node is connected: nobody can be served

``sellable`` (stored in ``panels.health_detail``) is what the sell-guard reads: only ``unhealthy`` panels leave server selection, so
a ``degraded`` panel keeps selling while the admin is told which node to fix. Existing accounts are never touched by this.
"""

import datetime as dt
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.domain.panel_health import DEGRADED, HEALTHY, SELLABLE_STATES, UNHEALTHY  # noqa: F401
from melorin.kernel.models.vpn import Panel, PanelNode
from melorin.modules.vpn import capabilities as panel_caps
from melorin.modules.vpn.adapters.base import PanelError, supports

log = logging.getLogger("melorin.vpn.health")

MAX_REASONS = 20

NODE_OK, NODE_CONNECTING, NODE_DISABLED = "connected", "connecting", "disabled"
NODE_BAD = ("error", "limited", "unknown")


def node_error_hint(message: str | None) -> str | None:
    """A fix suggestion for the common node failures (shown to the admin next to the raw panel message)."""
    text = (message or "").lower()
    if not text:
        return None
    if "certificate_verify_failed" in text or "self-signed" in text or "self signed" in text:
        return "گواهی TLS نود معتبر نیست: server_ca نود را در پنل تنظیم کنید یا گواهی معتبر نصب کنید (تأیید TLS را خاموش نکنید)."
    if "timed out" in text or "timeout" in text:
        return "نود پاسخ نمی‌دهد: وضعیت سرور نود و فایروال/پورت اتصال پنل به نود را بررسی کنید."
    if "refused" in text or "unreachable" in text or "no route" in text:
        return "اتصال به نود برقرار نمی‌شود: سرویس نود روشن و پورت آن باز باشد."
    if "name or service not known" in text or "getaddrinfo" in text or "nodename" in text:
        return "آدرس نود قابل resolve نیست: DNS یا آدرس نود را بررسی کنید."
    return None


@dataclass
class NodeSummary:
    total: int = 0
    connected: int = 0
    connecting: int = 0
    disabled: int = 0
    error: int = 0  # error + limited + unknown
    reasons: list[dict] = field(default_factory=list)

    @property
    def enabled(self) -> int:
        return self.total - self.disabled

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "connected": self.connected,
            "connecting": self.connecting,
            "disabled": self.disabled,
            "error": self.error,
        }


@dataclass
class HealthResult:
    status: str
    error: str | None = None
    detail: dict = field(default_factory=dict)
    node_changes: list[dict] = field(default_factory=list)  # {"name", "from", "to", "message"} for the Event Center


def summarize(nodes: list[dict]) -> NodeSummary:
    s = NodeSummary(total=len(nodes))
    for n in nodes:
        status = str(n.get("status") or "unknown").lower()
        if status == NODE_OK:
            s.connected += 1
        elif status == NODE_CONNECTING:
            s.connecting += 1
        elif status == NODE_DISABLED:
            s.disabled += 1
        else:
            s.error += 1
            if len(s.reasons) < MAX_REASONS:
                msg = str(n.get("message") or "")[:300] or None
                s.reasons.append(
                    {"node": str(n.get("name") or n.get("id")), "status": status, "message": msg, "hint": node_error_hint(msg)}
                )
    return s


def classify(summary: NodeSummary) -> tuple[str, str | None]:
    """(state, reason) from node counts. No nodes at all is NOT a verdict: the panel may keep its capacity elsewhere."""
    if summary.total == 0:
        return HEALTHY, None
    if summary.enabled == 0:
        return UNHEALTHY, "همهٔ نودهای پنل غیرفعال هستند"
    if summary.connected == 0:
        return UNHEALTHY, f"هیچ نود فعالی متصل نیست ({summary.error} نود خطا، {summary.connecting} در حال اتصال)"
    if summary.error:
        return DEGRADED, f"{summary.error} از {summary.enabled} نود فعال خطا دارد"
    return HEALTHY, None


def _node_row_changes(rows: dict[int, PanelNode], nodes: list[dict], panel_id, now: dt.datetime, session) -> list[dict]:
    """Upsert ``panel_nodes`` and return the status transitions worth telling an admin about."""
    changes: list[dict] = []
    seen: set[int] = set()
    for n in nodes:
        try:
            rid = int(n["id"])
        except (KeyError, TypeError, ValueError):
            continue
        seen.add(rid)
        status = str(n.get("status") or "unknown").lower()
        message = str(n.get("message") or "")[:1000] or None
        row = rows.get(rid)
        coef = n.get("usage_coefficient")
        if row is None:
            row = PanelNode(panel_id=panel_id, remote_id=rid, name=str(n.get("name") or rid)[:120], status=status, status_changed_at=now)
            session.add(row)
            rows[rid] = row
            if status in NODE_BAD:
                changes.append({"name": row.name, "from": None, "to": status, "message": message})
        elif row.status != status:
            if row.status in NODE_BAD or status in NODE_BAD:
                changes.append({"name": row.name, "from": row.status, "to": status, "message": message})
            row.status, row.status_changed_at = status, now
        row.name, row.message, row.removed_at = str(n.get("name") or rid)[:120], message, None
        row.xray_version = str(n.get("xray_version") or "")[:40] or None
        row.usage_coefficient = float(coef) if isinstance(coef, int | float) and not isinstance(coef, bool) else None
        if status == NODE_OK:
            row.last_seen_at = now
    for rid, row in rows.items():
        if rid not in seen and row.removed_at is None:
            row.removed_at = now
    return changes


async def check_panel(session: AsyncSession, panel: Panel, adapter, *, now: dt.datetime | None = None) -> HealthResult:
    """Run both layers against ``adapter`` and return the verdict. Writes ``panel_nodes`` rows; the caller stores the verdict on the
    panel (see :func:`apply`) and commits."""
    now = now or utcnow()
    try:
        ok = await adapter.health_check()
    except PanelError as exc:
        return HealthResult(UNHEALTHY, exc.message[:300], {"layer": 1, "sellable": False, "checked_at": now.isoformat()})
    if not ok:
        return HealthResult(UNHEALTHY, "health check returned false", {"layer": 1, "sellable": False, "checked_at": now.isoformat()})

    detail: dict = {"layer": 1, "node_check": "skipped", "sellable": True, "checked_at": now.isoformat()}
    allowed = panel_caps.capabilities_of(panel).has("node_ops")  # the credential may not read nodes (e.g. an Operator role)
    if not (allowed and supports(adapter, "node_ops")):
        return HealthResult(HEALTHY, None, detail)
    try:
        nodes = await adapter.list_nodes()
    except PanelError as exc:  # layer 2 failing must not turn a working panel unhealthy: report it and fall back to layer 1
        detail.update(node_check="failed", node_error=exc.message[:200])
        return HealthResult(HEALTHY, None, detail)

    summary = summarize(nodes)
    state, reason = classify(summary)
    rows = {r.remote_id: r for r in (await session.scalars(select(PanelNode).where(PanelNode.panel_id == panel.id))).all()}
    changes = _node_row_changes(rows, nodes, panel.id, now, session)
    detail.update(layer=2, node_check="ok", nodes=summary.to_dict(), reasons=summary.reasons, sellable=state in SELLABLE_STATES)
    if reason:
        detail["reason"] = reason
    return HealthResult(state, reason if state == UNHEALTHY else None, detail, changes)


def apply(panel: Panel, result: HealthResult, now: dt.datetime | None = None) -> str:
    """Store the verdict on the panel; returns the status the panel had BEFORE (what the Event Center compares with)."""
    previous = panel.health_status
    panel.health_status, panel.last_health_at = result.status, now or utcnow()
    panel.last_health_error = result.error
    panel.health_detail = result.detail
    return previous
