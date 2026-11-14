"""Admin API - real capacity and sellability of destinations (PG-08).

``GET  /admin/panels/{id}/capacity``          live state of every group (health, hosts, nodes, panel users) + every server's fill
``POST /admin/panels/{id}/capacity/refresh``  run the same check the health job runs, now, and store the verdicts
The destination picker (``/admin/panels/{id}/targets``) shows the same per-group ``health`` so a broken group is never picked blindly.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import NotFound
from melorin.kernel.models.vpn import Panel
from melorin.modules.panelops import queries
from melorin.modules.panelops.panel_probes import live_group_health, refresh_panel_capacity
from melorin.modules.panel_integrations import capabilities as panel_caps
from melorin.modules.panel_integrations import capacity

router = APIRouter(prefix="/admin", tags=["admin"])


async def _panel(session, panel_id: uuid.UUID) -> Panel:
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    return panel


@router.get("/panels/{panel_id}/capacity")
async def panel_capacity(panel_id: uuid.UUID, _: AdminUser, session: Session):
    panel = await _panel(session, panel_id)
    servers = await queries.servers_of_panel(session, panel.id, by_name=True)
    counts = await capacity.active_counts(session, [s.id for s in servers])
    return {
        "panel_id": panel.id,
        "panel_health": panel.health_status,
        "capacity_ops": panel_caps.capabilities_of(panel).has("capacity_ops"),
        "groups": await live_group_health(panel),
        "servers": [
            {
                "id": s.id,
                "name": s.name,
                "enabled": bool(s.is_enabled),
                "target": s.target,
                "sellable": bool(s.sellable),
                "sellable_reason": s.sellable_reason,
                "health": s.destination_health,
                "checked_at": s.capacity_checked_at,
                "capacity_info": capacity.capacity_view(s, counts.get(s.id, 0)),
            }
            for s in servers
        ],
    }


@router.post("/panels/{panel_id}/capacity/refresh")
async def refresh_capacity(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    panel = await _panel(session, panel_id)
    changes = await refresh_panel_capacity(session, panel)
    audit.record(
        session,
        "panel.capacity_refreshed",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="panel",
        entity_id=panel.id,
        data={"changes": [{"server": c.server, "kind": c.kind, "to": c.new} for c in changes]},
    )
    await session.commit()
    return {"changes": [{"server": c.server, "kind": c.kind, "from": c.old, "to": c.new, "detail": c.detail} for c in changes]}
