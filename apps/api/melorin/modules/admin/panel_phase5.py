"""Admin API - PasarGuard Phase 5: panel readings for dashboards (PG-14), settings drift + lifecycle policy (PG-15), panel backup (PG-16).

Thin layer: every rule lives in ``modules/vpn/{panel_metrics,settings_drift,panel_backup}.py``. Admin session only. Nothing here writes a
setting to a panel: the drift check is read-only and the lifecycle policy only changes what Melorin expects."""

import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from melorin.core.deps import AdminUser, Session
from melorin.core.errors import NotFound
from melorin.kernel.models.vpn import Panel, PanelNode
from melorin.modules.vpn import panel_backup, panel_metrics, settings_drift

router = APIRouter(prefix="/admin", tags=["admin"])


# ------------------------------------------------------------------------------------------------------------------ PG-14 readings
@router.get("/panels/{panel_id}/metrics")
async def panel_readings(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    """The last live reading of the panel (what the Prometheus gauges are built from) plus its node counts."""
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    rows = (
        await session.execute(
            select(PanelNode.status, func.count())
            .where(PanelNode.panel_id == panel.id, PanelNode.removed_at.is_(None))
            .group_by(PanelNode.status)
        )
    ).all()
    nodes = dict.fromkeys(panel_metrics.NODE_STATES, 0)
    for status, n in rows:
        nodes[status if status in nodes else "error"] += int(n)
    snap = panel.metrics_snapshot if isinstance(panel.metrics_snapshot, dict) else None
    return {
        "panel_id": panel.id,
        "health_status": panel.health_status,
        "taken_at": panel.metrics_snapshot_at,
        "reading": snap,
        "nodes": nodes if rows else None,
        "fresh_minutes": int(panel_metrics.SNAPSHOT_FRESH.total_seconds() // 60),
    }


# ------------------------------------------------------------------------------------------------------------------ PG-15 drift
@router.get("/panels/{panel_id}/settings-drift")
async def drift_last(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    return settings_drift.describe(panel)


@router.post("/panels/{panel_id}/settings-drift/check")
async def drift_check(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    """Read the panel's settings now and compare. Read-only: no setting is written to the panel."""
    return await settings_drift.recheck(session, panel_id, actor_id=admin.id)


class LifecyclePolicyIn(BaseModel):
    policy: Literal["keep", "aligned"]
    reason: str = Field(min_length=3, max_length=300)


@router.put("/panels/{panel_id}/lifecycle-policy")
async def lifecycle_policy(panel_id: uuid.UUID, body: LifecyclePolicyIn, admin: AdminUser, session: Session):
    """Choose what Melorin expects of the panel's auto-delete of expired users (audited). Changes Melorin's expectation only."""
    return await settings_drift.set_policy(session, panel_id, body.policy, actor_id=admin.id, reason=body.reason)


# ------------------------------------------------------------------------------------------------------------------ PG-16 backup
@router.get("/panel-backups")
async def panel_backups(admin: AdminUser, session: Session):
    return await panel_backup.status(session)
