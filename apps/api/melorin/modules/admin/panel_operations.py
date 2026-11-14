"""Admin API - panel operations - operations console (PG-07), bulk operations (PG-11), store governance (PG-12), subscription test (PG-13).

Thin layer: every rule lives in ``modules/vpn_accounts/{ops_console,bulk,governance,subscription_check}.py``. Admin session only; every write is
audited by the service it calls."""

import uuid
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from melorin.core.deps import AdminUser, Session
from melorin.core.errors import NotFound
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import BulkOperation, Panel, PanelAdmin
from melorin.modules.panelops import bulk, governance, subscription_check
from melorin.modules.panelops import ops_console

from melorin.modules.panelops import queries

router = APIRouter(prefix="/admin", tags=["admin"])


# ------------------------------------------------------------------------------------------------------------------ PG-07 console
@router.get("/panels/{panel_id}/ops")
async def ops_overview(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    return await ops_console.overview(session, panel_id)


@router.get("/panels/{panel_id}/ops/infra")
async def ops_infra(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    return await ops_console.list_infra(session, panel_id)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/panels/{panel_id}/ops/nodes/{node_id}/{action}")
async def ops_node_action(
    panel_id: uuid.UUID, node_id: int, action: Literal["reconnect", "sync"], body: ReasonIn, admin: AdminUser, session: Session
):
    return await ops_console.node_action(session, panel_id, node_id, action, admin_id=admin.id, reason=body.reason)


class CoreRestartIn(ReasonIn):
    confirm_name: str = Field(min_length=1, max_length=200)


@router.post("/panels/{panel_id}/ops/cores/{core_id}/restart")
async def ops_core_restart(panel_id: uuid.UUID, core_id: int, body: CoreRestartIn, admin: AdminUser, session: Session):
    return await ops_console.core_restart(session, panel_id, core_id, admin_id=admin.id, reason=body.reason, confirm_name=body.confirm_name)


class ToggleIn(ReasonIn):
    ids: list[int] = Field(min_length=1, max_length=ops_console.MAX_IDS)
    disabled: bool
    force: bool = False


@router.post("/panels/{panel_id}/ops/{family}/toggle")
async def ops_toggle(panel_id: uuid.UUID, family: Literal["nodes", "hosts", "groups"], body: ToggleIn, admin: AdminUser, session: Session):
    return await ops_console.toggle(
        session, panel_id, family, body.ids, body.disabled, admin_id=admin.id, reason=body.reason, force=body.force
    )


# ------------------------------------------------------------------------------------------------------------------ PG-13 subscription test
@router.get("/panels/{panel_id}/subscription-check")
async def subscription_check_last(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    return {"checked_at": panel.subscription_checked_at, "result": panel.subscription_check}


@router.post("/panels/{panel_id}/subscription-check")
async def subscription_check_run(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    return await subscription_check.run(session, panel_id, actor_id=admin.id)


# ------------------------------------------------------------------------------------------------------------------ PG-11 bulk operations
class SelectionIn(BaseModel):
    panel_id: uuid.UUID
    store_id: uuid.UUID | None = None
    server_id: uuid.UUID | None = None
    statuses: list[str] = Field(default_factory=list, max_length=6)
    expiring_within_days: int | None = Field(default=None, ge=0, le=3650)
    usernames: list[str] = Field(default_factory=list, max_length=bulk.MAX_ITEMS)


class BulkPreviewIn(BaseModel):
    kind: Literal["disable", "enable", "reset_usage", "rotate_links", "extend_days", "add_traffic"]
    selection: SelectionIn
    params: dict | None = None
    reason: str = Field(min_length=3, max_length=300)


class BulkConfirmIn(BaseModel):
    count: int = Field(ge=1)


def op_out(op: BulkOperation, *, panel_name: str | None = None, store_name: str | None = None) -> dict:
    return {
        "id": op.id,
        "panel_id": op.panel_id,
        "panel_name": panel_name,
        "store_id": op.store_id,
        "store_name": store_name,
        "kind": op.kind,
        "kind_label": bulk.KIND_LABELS.get(op.kind, op.kind),
        "params": op.params,
        "selection": op.selection,
        "reason": op.reason,
        "origin": op.origin,
        "status": op.status,
        "total": op.total,
        "succeeded": op.succeeded,
        "failed": op.failed,
        "skipped": op.skipped,
        "sample": op.sample,
        "error": op.error,
        "created_at": op.created_at,
        "confirmed_at": op.confirmed_at,
        "started_at": op.started_at,
        "finished_at": op.finished_at,
        "expires_at": op.expires_at,
    }


async def _named(session, op: BulkOperation) -> dict:
    panel = await session.get(Panel, op.panel_id)
    store = await session.get(Store, op.store_id) if op.store_id else None
    return op_out(op, panel_name=panel.name if panel else None, store_name=store.name if store else None)


@router.post("/bulk-operations/preview")
async def bulk_preview(body: BulkPreviewIn, admin: AdminUser, session: Session):
    sel = bulk.Selection(**body.selection.model_dump())
    op = await bulk.preview(session, kind=body.kind, selection=sel, params=body.params, reason=body.reason, actor_id=admin.id)
    return await _named(session, op)


@router.get("/bulk-operations")
async def bulk_list(
    admin: AdminUser,
    session: Session,
    status: str | None = None,
    panel_id: uuid.UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    total, rows = await queries.bulk_operation_rows(session, status=status, panel_id=panel_id, limit=limit, offset=offset)
    return {"total": total, "items": [await _named(session, r) for r in rows]}


@router.get("/bulk-operations/{op_id}")
async def bulk_detail(
    op_id: uuid.UUID,
    admin: AdminUser,
    session: Session,
    item_status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    op = await bulk.get(session, op_id)
    items = await bulk.items_page(session, op_id, status=item_status, limit=limit, offset=offset)
    return {**await _named(session, op), "items": [bulk.item_out(i) for i in items]}


@router.post("/bulk-operations/{op_id}/confirm")
async def bulk_confirm(op_id: uuid.UUID, body: BulkConfirmIn, admin: AdminUser, session: Session):
    return await _named(session, await bulk.confirm(session, op_id, count=body.count, actor_id=admin.id))


@router.post("/bulk-operations/{op_id}/cancel")
async def bulk_cancel(op_id: uuid.UUID, admin: AdminUser, session: Session):
    return await _named(session, await bulk.cancel(session, op_id, actor_id=admin.id))


@router.post("/bulk-operations/{op_id}/resume")
async def bulk_resume(op_id: uuid.UUID, admin: AdminUser, session: Session):
    return await _named(session, await bulk.resume(session, op_id, actor_id=admin.id))


# ------------------------------------------------------------------------------------------------------------------ PG-12 governance
class GovernanceIn(BaseModel):
    data_limit_gb: float | None = Field(default=None, gt=0, le=governance.MAX_CAP_GB)
    clear_limit: bool = False
    status: Literal["active", "disabled"] | None = None
    notifications_off: bool | None = None
    reason: str | None = Field(default=None, max_length=300)


class StorePolicyIn(BaseModel):
    suspend_policy: Literal["none", "disable_accounts"]


@router.get("/store-admins")
async def governance_list(admin: AdminUser, session: Session, panel_id: uuid.UUID | None = None):
    rows = await queries.store_admin_rows(session, panel_id)
    return {"items": [governance.row_out(a, s, p) for a, s, p in rows]}


@router.post("/store-admins/refresh")
async def governance_refresh(admin: AdminUser, session: Session, panel_id: uuid.UUID | None = None):
    """Read usage now instead of waiting for the periodic job."""
    out = {"checked": 0, "updated": 0, "errors": 0}
    for panel in await queries.pasarguard_panels(session, panel_id):
        stats = await governance.sync_usage(session, panel)
        out["checked"] += stats.checked
        out["updated"] += stats.updated
        out["errors"] += stats.errors
    await session.commit()
    return out


@router.patch("/store-admins/{row_id}")
async def governance_update(row_id: uuid.UUID, body: GovernanceIn, admin: AdminUser, session: Session):
    row = await session.get(PanelAdmin, row_id)
    if not row:
        raise NotFound("ادمین فروشگاه")
    await governance.set_limits(
        session, row, actor_id=admin.id, data_limit_gb=body.data_limit_gb, clear_limit=body.clear_limit,
        status=body.status, notifications_off=body.notifications_off, reason=body.reason,
    )  # fmt: skip
    store, panel = await session.get(Store, row.store_id), await session.get(Panel, row.panel_id)
    return governance.row_out(row, store, panel)


@router.put("/resellers/{store_id}/suspend-policy")
async def set_suspend_policy(store_id: uuid.UUID, body: StorePolicyIn, admin: AdminUser, session: Session):
    """Opt a store in/out of "suspension also disables its panel admin and accounts". Takes effect on the NEXT suspension."""
    from melorin.core import audit

    store = await session.get(Store, store_id)
    if not store or store.kind != "reseller":
        raise NotFound("فروشگاه نماینده")
    before = store.suspend_policy
    store.suspend_policy = body.suspend_policy
    if before != body.suspend_policy:
        audit.record(
            session, "reseller.suspend_policy", actor_id=admin.id, actor_type="admin", entity_type="reseller_store", entity_id=store.id,
            store_id=store.id, data={"before": before, "after": body.suspend_policy},
        )  # fmt: skip
    await session.commit()
    return {"store_id": store.id, "suspend_policy": store.suspend_policy}
