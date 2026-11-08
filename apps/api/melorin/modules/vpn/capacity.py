"""Real capacity and sellability of a destination (PG-08): layer 3 of panel health.

A server (destination) points at PasarGuard groups or a user template. A destination is only worth selling when customers created
there can actually connect:  group enabled -> at least one enabled host on one of its inbound tags -> at least one connected node
that runs those inbounds.  Layers 1-2 (panel answers, nodes) live in :mod:`melorin.modules.vpn.health`.

Pure functions first (``assess_group``, ``assess_server``, ``fill_state``), then one loader (:func:`refresh_panel`) that the health job
calls with a live adapter. Rules that matter:

* **Fail open.** A check that cannot run (no permission, panel error, unknown target) never removes a destination from sale: the last
  known verdict stays and the detail says ``check: skipped|failed``. Only a positive finding ("no enabled host", "no connected node",
  "group disabled on the panel") sets ``sellable=False``.
* **Existing accounts are never touched.** ``sellable`` only filters NEW orders (see ``catalog.allocation.routing``).
* **Capacity source.** ``melorin`` (default) counts the accounts Melorin sold; ``panel`` takes the larger of that and the panel's own
  ``total_users`` of the group, so users created outside Melorin also fill the destination. The panel figure is only trusted for a
  target made of exactly ONE group (several groups would count a user twice).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.vpn import Panel, Server, VpnAccount
from melorin.modules.vpn import capabilities as panel_caps
from melorin.modules.vpn.adapters.base import PanelError, supports
from melorin.modules.vpn.targets import effective_destination

log = logging.getLogger("melorin.vpn.capacity")

OK, DEGRADED, BLOCKED = "healthy", "degraded", "blocked"
CAPACITY_SOURCES = ("melorin", "panel")
WARN_AT, CRITICAL_AT, FULL_AT = 80, 95, 100  # percent of capacity
NODE_OK = "connected"
_LOAD_STATUSES = (VpnStatus.ACTIVE, VpnStatus.PROVISIONING)


# ---------------------------------------------------------------------------------------------------------------- pure rules
@dataclass
class Assessment:
    status: str = OK
    score: int = 100
    reasons: list[str] = field(default_factory=list)
    hosts: int = 0  # enabled hosts reachable through the destination's inbounds
    nodes: int = 0  # connected nodes that serve them
    total_users: int | None = None  # the panel's own count (a single group only)

    @property
    def sellable(self) -> bool:
        return self.status != BLOCKED

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "score": self.score,
            "reasons": self.reasons[:10],
            "hosts": self.hosts,
            "nodes": self.nodes,
            "total_users": self.total_users,
        }


def _tags(group: dict) -> list[str]:
    return [str(t) for t in (group.get("inbound_tags") or []) if t]


def tag_cores(inbounds: list[dict]) -> dict[str, set[int]]:
    """inbound tag -> the core config ids that define it, when the panel says so (``core_config_id`` / ``core_id``); else empty."""
    out: dict[str, set[int]] = {}
    for row in inbounds or []:
        tag = row.get("tag") or row.get("inbound_tag")
        core = row.get("core_config_id", row.get("core_id"))
        if tag and isinstance(core, int) and not isinstance(core, bool):
            out.setdefault(str(tag), set()).add(core)
    return out


def assess_group(group: dict, hosts: list[dict], nodes: list[dict], cores: dict[str, set[int]] | None = None) -> Assessment:
    """Can a customer created in ``group`` connect right now? ``blocked`` only on a positive finding."""
    a = Assessment(total_users=group.get("total_users") if isinstance(group.get("total_users"), int) else None)
    if group.get("is_disabled"):
        a.status, a.score = BLOCKED, 0
        a.reasons.append("گروه روی پنل غیرفعال است")
        return a
    tags = _tags(group)
    if not tags:
        a.status, a.score = BLOCKED, 0
        a.reasons.append("گروه هیچ inbound ندارد؛ کاربرِ این گروه به هیچ سرویسی وصل نمی‌شود")
        return a

    live_hosts = [h for h in hosts if not h.get("is_disabled") and str(h.get("inbound_tag") or "") in tags]
    tags_with_host = {str(h.get("inbound_tag")) for h in live_hosts}
    a.hosts = len(live_hosts)
    if not live_hosts:
        a.status, a.score = BLOCKED, 0
        a.reasons.append("هیچ هاست فعالی روی inbound های این گروه نیست")
        return a
    for tag in tags:
        if tag not in tags_with_host:
            a.reasons.append(f"inbound «{tag}» هاست فعال ندارد")

    known_cores = {c for t in tags_with_host for c in (cores or {}).get(t, set())}
    relevant = [n for n in nodes if str(n.get("status") or "").lower() != "disabled"]
    if known_cores:  # the panel told us which core runs these inbounds: only those nodes matter
        relevant = [n for n in relevant if n.get("core_config_id") in known_cores]
    connected = [n for n in relevant if str(n.get("status") or "").lower() == NODE_OK]
    a.nodes = len(connected)
    if nodes and not connected:  # no node data at all is NOT a verdict (this credential may not read nodes)
        a.status, a.score = BLOCKED, 0
        a.reasons.append("هیچ نود متصلی این گروه را سرویس نمی‌دهد")
        return a
    bad = len(relevant) - len(connected)
    if bad:
        a.reasons.append(f"{bad} از {len(relevant)} نود مرتبط خطا دارد")
    missing_tags = len([t for t in tags if t not in tags_with_host])
    if bad or missing_tags:
        a.status = DEGRADED
    node_part = (len(connected) / len(relevant)) if relevant else 1.0
    tag_part = (len(tags_with_host) / len(tags)) if tags else 1.0
    a.score = max(1, min(99, round(100 * (0.5 * node_part + 0.5 * tag_part)))) if a.status == DEGRADED else 100
    return a


def assess_template(template: dict | None, groups: dict[int, Assessment]) -> Assessment:
    """A template creates users in ALL its groups: it sells while at least one of them can serve customers."""
    a = Assessment()
    if template is None:
        a.reasons.append("تمپلیت روی پنل پیدا نشد")
        a.status, a.score = BLOCKED, 0
        return a
    if template.get("is_disabled"):
        a.status, a.score = BLOCKED, 0
        a.reasons.append("تمپلیت روی پنل غیرفعال است")
        return a
    ids = [int(g) for g in (template.get("group_ids") or [])]
    return combine([groups.get(g) for g in ids], missing_reason="تمپلیت گروه معتبری ندارد")


def combine(parts: list[Assessment | None], *, missing_reason: str = "گروه روی پنل پیدا نشد") -> Assessment:
    """Merge several group verdicts: blocked only when ALL are blocked; degraded when some are."""
    a = Assessment()
    known = [p for p in parts if p is not None]
    for p in parts:
        if p is None:
            a.reasons.append(missing_reason)
    if not known:
        a.status, a.score = BLOCKED, 0
        return a
    usable = [p for p in known if p.sellable]
    a.hosts, a.nodes = sum(p.hosts for p in usable), sum(p.nodes for p in usable)
    for p in known:
        a.reasons.extend(p.reasons)
    if not usable:
        a.status, a.score = BLOCKED, 0
    elif len(usable) < len(parts) or any(p.status == DEGRADED for p in usable):
        a.status = DEGRADED
        a.score = round(sum(p.score for p in usable) / len(parts))
    if len(known) == 1 and len(parts) == 1:
        a.total_users = known[0].total_users
    return a


def target_of(panel: Panel, server: Server) -> dict:
    return effective_destination(panel.kind, panel.config, server.target)


def assess_server(panel: Panel, server: Server, groups: dict[int, Assessment], templates: dict[int, dict] | None) -> Assessment | None:
    """Verdict for one server, or ``None`` when its target is not something this check understands (then nothing changes)."""
    target = target_of(panel, server)
    if "user_template_id" in target:
        if templates is None:
            return None
        return assess_template(templates.get(int(target["user_template_id"])), groups)
    gids = [int(g) for g in (target.get("group_ids") or [])]
    if not gids:
        return None
    return combine([groups.get(g) for g in gids])


def fill_percent(used: int, capacity: int) -> int:
    return 100 if capacity <= 0 else int(used * 100 / capacity)


def fill_state(used: int, capacity: int) -> str:
    """ok | warning (>=80%) | critical (>=95%) | full (>=100%)."""
    pct = fill_percent(used, capacity)
    return "full" if pct >= FULL_AT else "critical" if pct >= CRITICAL_AT else "warning" if pct >= WARN_AT else "ok"


def alert_level(used: int, capacity: int) -> int:
    """The highest announced threshold the fill has reached: 0 | 80 | 95 | 100."""
    pct = fill_percent(used, capacity)
    return FULL_AT if pct >= FULL_AT else CRITICAL_AT if pct >= CRITICAL_AT else WARN_AT if pct >= WARN_AT else 0


def effective_load(server: Server, melorin_active: int) -> int:
    """What counts against ``capacity``: Melorin's own accounts, or (source=panel) the larger of that and the panel's count."""
    if server.capacity_source == "panel" and server.panel_total_users is not None:
        return max(melorin_active, int(server.panel_total_users))
    return melorin_active


def capacity_view(server: Server, melorin_active: int) -> dict:
    """The numbers the admin sees next to a destination, from one place so the list, the picker and alerts agree."""
    used = effective_load(server, melorin_active)
    return {
        "capacity": int(server.capacity or 0),
        "melorin_accounts": melorin_active,
        "panel_users": server.panel_total_users,
        "outside_melorin": max(0, int(server.panel_total_users) - melorin_active) if server.panel_total_users is not None else None,
        "source": server.capacity_source,
        "panel_users_as_of": server.capacity_checked_at,  # R7: a stored panel number is always shown with its age
        "used": used,
        "percent": fill_percent(used, int(server.capacity or 0)),
        "state": fill_state(used, int(server.capacity or 0)),
    }


# ---------------------------------------------------------------------------------------------------------------- loader
async def active_counts(session: AsyncSession, server_ids: list) -> dict:
    if not server_ids:
        return {}
    rows = await session.execute(
        select(VpnAccount.server_id, func.count())
        .where(VpnAccount.server_id.in_(server_ids), VpnAccount.status.in_(_LOAD_STATUSES))
        .group_by(VpnAccount.server_id)
    )
    return {sid: int(n) for sid, n in rows.all()}


async def fetch_assessments(adapter) -> tuple[dict[int, Assessment], dict[int, dict]]:
    """Read groups, hosts, inbounds, nodes and templates once and assess every group. Raises ``PanelError`` when groups/hosts fail."""
    groups = await adapter.list_groups_full()
    hosts = await adapter.list_hosts()
    try:
        cores = tag_cores(await adapter.list_inbound_details())
    except PanelError:
        cores = {}  # optional refinement: without it every connected node counts
    nodes: list[dict] = []
    if supports(adapter, "node_ops"):
        try:
            nodes = await adapter.list_nodes()
        except PanelError:
            nodes = []
    assessed = {int(g["id"]): assess_group(g, hosts, nodes, cores) for g in groups}
    templates: dict[int, dict] = {}
    if hasattr(adapter, "list_templates"):
        try:
            templates = {int(t["id"]): t for t in await adapter.list_templates() if t.get("id") is not None}
        except PanelError:
            templates = {}
    return assessed, templates


@dataclass
class Change:
    server: str
    kind: str  # sellable | capacity
    old: str | None
    new: str
    detail: str | None = None


async def refresh_panel(session: AsyncSession, panel: Panel, adapter, *, now: dt.datetime | None = None) -> list[Change]:
    """Update every server of ``panel`` from the live panel and return the transitions worth telling an admin. Never raises."""
    now = now or utcnow()
    servers = (await session.scalars(select(Server).where(Server.panel_id == panel.id))).all()
    if not servers:
        return []
    allowed = panel_caps.capabilities_of(panel).has("capacity_ops")
    counts = await active_counts(session, [s.id for s in servers])
    assessed: dict[int, Assessment] = {}
    templates: dict[int, dict] | None = None
    check = "skipped"
    if allowed and supports(adapter, "capacity_ops"):
        try:
            assessed, templates = await fetch_assessments(adapter)
            check = "ok"
        except PanelError as exc:
            check = "failed"
            log.info("capacity check failed panel=%s: %s", panel.id, exc.message)
        except Exception:
            check = "failed"
            log.warning("capacity check crashed panel=%s", panel.id, exc_info=True)

    changes: list[Change] = []
    for s in servers:
        s.capacity_checked_at = now
        verdict = assess_server(panel, s, assessed, templates) if check == "ok" else None
        if verdict is not None:
            was = bool(s.sellable)
            s.sellable, s.sellable_reason = verdict.sellable, ("؛ ".join(verdict.reasons)[:300] or None) if not verdict.sellable else None
            s.destination_health = {**verdict.to_dict(), "check": "ok", "checked_at": now.isoformat()}
            s.panel_total_users = verdict.total_users
            if was != s.sellable and s.is_enabled:
                changes.append(
                    Change(s.name, "sellable", "sellable" if was else "blocked", "sellable" if s.sellable else "blocked", s.sellable_reason)
                )
        else:
            detail = dict(s.destination_health or {})
            detail.update(check=check, checked_at=now.isoformat())
            s.destination_health = detail  # keep the last verdict; only say that the latest check did not produce a new one
        level = alert_level(effective_load(s, counts.get(s.id, 0)), int(s.capacity or 0))
        if s.is_enabled and level > (s.capacity_alert_level or 0):
            changes.append(Change(s.name, "capacity", str(s.capacity_alert_level or 0), str(level)))
        s.capacity_alert_level = level  # also falls back, so the next climb is announced again
    return changes
