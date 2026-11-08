"""Admin API - PasarGuard Phase 5: panel readings for dashboards (PG-14), settings drift + lifecycle policy (PG-15), panel backup (PG-16).

Thin layer: every rule lives in ``modules/vpn/{panel_metrics,settings_drift,panel_backup}.py``. Admin session only. Nothing here writes a
setting to a panel: the drift check is read-only and the lifecycle policy only changes what Melorin expects."""

import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.vpn import Panel, PanelNode
from melorin.modules.vpn import panel_backup, panel_metrics, service_access, settings_drift, store_role

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
    retention_days: int | None = Field(
        default=None, ge=1, le=365, description="aligned only: the least days the panel must keep expired users"
    )
    reason: str = Field(min_length=3, max_length=300)


@router.put("/panels/{panel_id}/lifecycle-policy")
async def lifecycle_policy(panel_id: uuid.UUID, body: LifecyclePolicyIn, admin: AdminUser, session: Session):
    """Choose what Melorin expects of the panel's auto-delete of expired users (audited). Changes Melorin's expectation only."""
    return await settings_drift.set_policy(
        session, panel_id, body.policy, actor_id=admin.id, reason=body.reason, retention_days=body.retention_days
    )


# ------------------------------------------------------------------------------------------------------------------ PG-16 backup
@router.get("/panel-backups")
async def panel_backups(admin: AdminUser, session: Session):
    return await panel_backup.status(session)


# ------------------------------------------------------------------------------------------------------------------ PG-05 service access
class BootstrapIn(BaseModel):
    """An OWNER credential for this one request. Never stored, never logged, never returned."""

    api_key: str | None = Field(default=None, repr=False, max_length=512)
    username: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, repr=False, max_length=512)

    def as_dict(self) -> dict | None:
        data = {k: v for k, v in self.model_dump().items() if v}
        return data or None


class ServiceAccessIn(BaseModel):
    confirm_name: str = Field(description="the panel's name, typed by the admin: this creates a role, an admin and a key on the PANEL")
    bootstrap: BootstrapIn | None = None


async def _service_panel(session, panel_id: uuid.UUID, confirm_name: str) -> Panel:
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    if confirm_name.strip() != panel.name:
        raise AppError("CONFIRM_REQUIRED", "نام پنل را برای تأیید دقیقاً وارد کنید.", 422)
    return panel


@router.get("/panels/{panel_id}/store-role-plan")
async def store_role_plan(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    """PG-12: the least-privilege role a store's panel admin should have (read-only plan; Melorin does not create it on the panel)."""
    if not await session.get(Panel, panel_id):
        raise NotFound("پنل")
    return store_role.plan()


@router.get("/panels/{panel_id}/service-access")
async def service_access_status(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    """Which credential level Melorin runs on, whether the service admin exists, and exactly what its role grants / withholds."""
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    return await service_access.status(panel)


@router.post("/panels/{panel_id}/service-access/keys")
async def service_access_keys(panel_id: uuid.UUID, body: BootstrapIn, admin: AdminUser, session: Session):
    """The service admin's keys as the panel lists them (name, status, request count; never values). Needs an owner credential once."""
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    if body.as_dict() is None:
        raise AppError("BOOTSTRAP_REQUIRED", "برای فهرست کلیدها یک اعتبارنامهٔ owner لازم است.", 422)
    return await service_access.status(panel, bootstrap=body.as_dict())


@router.post("/panels/{panel_id}/service-access/provision")
async def service_access_provision(panel_id: uuid.UUID, body: ServiceAccessIn, admin: AdminUser, session: Session):
    """Create the least-privilege admin + key, verify it, then switch Melorin to it. The old owner key is left for you to revoke."""
    panel = await _service_panel(session, panel_id, body.confirm_name)
    boot = body.bootstrap.as_dict() if body.bootstrap else None
    return await service_access.provision(session, panel, bootstrap=boot, actor_id=admin.id)


@router.post("/panels/{panel_id}/service-access/rotate")
async def service_access_rotate(panel_id: uuid.UUID, body: ServiceAccessIn, admin: AdminUser, session: Session):
    """Replace the service key (new key verified before the switch, old key deleted after). Needs an owner credential once."""
    panel = await _service_panel(session, panel_id, body.confirm_name)
    boot = body.bootstrap.as_dict() if body.bootstrap else None
    if boot is None:
        raise AppError("BOOTSTRAP_REQUIRED", "برای چرخش کلید یک اعتبارنامهٔ owner لازم است.", 422)
    return await service_access.rotate(session, panel, bootstrap=boot, actor_id=admin.id)
