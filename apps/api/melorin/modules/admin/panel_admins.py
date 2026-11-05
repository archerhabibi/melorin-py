"""Admin API - the PasarGuard admin (Operator) of each store, its optional "Profile & contact", and reseller change requests."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from melorin.core import audit
from melorin.core.crypto import decrypt
from melorin.core.db import utcnow
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import Panel, PanelAdmin, PanelAdminChangeRequest
from melorin.modules.vpn import panel_admins as svc
from melorin.modules.vpn.adapters.base import PanelError

router = APIRouter(prefix="/admin", tags=["admin"])


class ProfileIn(BaseModel):
    store_id: uuid.UUID
    panel_id: uuid.UUID | None = None  # None = every panel of the store
    profile: dict = Field(default_factory=dict)


class SyncIn(BaseModel):
    panel_id: uuid.UUID | None = None


class ReviewIn(BaseModel):
    changes: dict | None = None  # the admin may edit what the reseller asked for before applying
    note: str | None = Field(default=None, max_length=500)


def _bad(exc: svc.ProfileError) -> AppError:
    return AppError("PROFILE_INVALID", str(exc), 422)


async def _out(session, rows):
    panels, stores = {}, {}
    out = []
    for r in rows:
        panels[r.panel_id] = panels.get(r.panel_id) or await session.get(Panel, r.panel_id)
        stores[r.store_id] = stores.get(r.store_id) or await session.get(Store, r.store_id)
        out.append(svc.public_row(r, panel=panels[r.panel_id], store=stores[r.store_id]))
    return out


@router.get("/panel-admins")
async def list_panel_admins(_: AdminUser, session: Session, store_id: uuid.UUID | None = None, panel_id: uuid.UUID | None = None):
    stmt = select(PanelAdmin).order_by(PanelAdmin.created_at)
    if store_id:
        stmt = stmt.where(PanelAdmin.store_id == store_id)
    if panel_id:
        stmt = stmt.where(PanelAdmin.panel_id == panel_id)
    return await _out(session, (await session.scalars(stmt)).all())


@router.post("/panel-admins/sync")
async def sync_panel_admins(body: SyncIn, admin: AdminUser, session: Session):
    """Create every missing Operator admin now (the worker does the same every minute) and move existing accounts under them."""
    panel = None
    if body.panel_id:
        panel = await session.get(Panel, body.panel_id)
        if not panel:
            raise NotFound("پنل")
    result = await svc.sync_all(session, limit=200, panel=panel)
    audit.record(session, "panel_admin.sync", actor_id=admin.id, actor_type="admin", data=result)
    await session.commit()
    return result


@router.patch("/panel-admins/profile")
async def edit_profile(body: ProfileIn, admin: AdminUser, session: Session):
    """Optional "Profile & contact" of a store's admin. Only the Melorin admin can do this."""
    try:
        results = await svc.apply_profile(session, body.store_id, body.profile, panel_id=body.panel_id)
    except svc.ProfileError as exc:
        raise _bad(exc) from exc
    if not results:
        raise NotFound("ادمین پنل")
    audit.record(
        session, "panel_admin.profile_updated", actor_id=admin.id, actor_type="admin", entity_type="store", entity_id=body.store_id,
        store_id=body.store_id, data={"fields": sorted(body.profile)},
    )
    await session.commit()
    return {"results": results}


async def _row(session, row_id: uuid.UUID) -> PanelAdmin:
    row = await session.get(PanelAdmin, row_id)
    if not row:
        raise NotFound("ادمین پنل")
    return row


@router.get("/panel-admins/{row_id}/credentials")
async def credentials(row_id: uuid.UUID, admin: AdminUser, session: Session):
    """Login of the store's admin on the PasarGuard dashboard (shown to the Melorin admin only; every view is audited)."""
    row = await _row(session, row_id)
    panel = await session.get(Panel, row.panel_id)
    audit.record(session, "panel_admin.credentials_viewed", actor_id=admin.id, actor_type="admin", entity_type="panel_admin", entity_id=row.id,
                 store_id=row.store_id)
    await session.commit()
    return {"username": row.username, "password": decrypt(row.password_enc), "panel_url": panel.base_url if panel else None, "status": row.status}


@router.post("/panel-admins/{row_id}/reset-password")
async def reset_password(row_id: uuid.UUID, admin: AdminUser, session: Session):
    row = await _row(session, row_id)
    panel = await session.get(Panel, row.panel_id)
    try:
        password = await svc.reset_password(session, row, panel)
    except PanelError as exc:
        raise AppError("PANEL_ERROR", exc.message, 502) from exc
    audit.record(session, "panel_admin.password_reset", actor_id=admin.id, actor_type="admin", entity_type="panel_admin", entity_id=row.id,
                 store_id=row.store_id)
    await session.commit()
    return {"username": row.username, "password": password}


# ----- reseller change requests -----
def _req_out(r: PanelAdminChangeRequest, store_name: str | None) -> dict:
    return {
        "id": r.id, "store_id": r.store_id, "store_name": store_name, "changes": r.changes, "message": r.message, "status": r.status,
        "created_at": r.created_at, "reviewed_at": r.reviewed_at, "review_note": r.review_note,
    }


@router.get("/panel-admin-requests")
async def list_requests(_: AdminUser, session: Session, status: str | None = "pending"):
    stmt = select(PanelAdminChangeRequest).order_by(PanelAdminChangeRequest.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(PanelAdminChangeRequest.status == status)
    rows = (await session.scalars(stmt)).all()
    stores = {}
    for r in rows:
        stores[r.store_id] = stores.get(r.store_id) or await session.get(Store, r.store_id)
    return [_req_out(r, stores[r.store_id].name if stores[r.store_id] else None) for r in rows]


async def _pending(session, request_id: uuid.UUID) -> PanelAdminChangeRequest:
    r = await session.get(PanelAdminChangeRequest, request_id, with_for_update=True)
    if not r:
        raise NotFound("درخواست")
    if r.status != "pending":
        raise AppError("REQUEST_ALREADY_REVIEWED", "این درخواست قبلاً بررسی شده است.", 409)
    return r


@router.post("/panel-admin-requests/{request_id}/apply")
async def apply_request(request_id: uuid.UUID, body: ReviewIn, admin: AdminUser, session: Session):
    r = await _pending(session, request_id)
    changes = body.changes if body.changes is not None else r.changes
    try:
        results = await svc.apply_profile(session, r.store_id, changes)
    except svc.ProfileError as exc:
        raise _bad(exc) from exc
    if not results:
        raise AppError("PANEL_ADMIN_MISSING", "برای این فروشگاه هنوز ادمینی روی پنل ساخته نشده است.", 409)
    r.status, r.reviewed_by, r.reviewed_at, r.review_note = "applied", admin.id, utcnow(), body.note
    audit.record(session, "panel_admin.request_applied", actor_id=admin.id, actor_type="admin", entity_type="store", entity_id=r.store_id,
                 store_id=r.store_id, data={"request_id": str(r.id), "fields": sorted(changes)})
    await session.commit()
    return {"ok": True, "results": results}


@router.post("/panel-admin-requests/{request_id}/reject")
async def reject_request(request_id: uuid.UUID, body: ReviewIn, admin: AdminUser, session: Session):
    r = await _pending(session, request_id)
    r.status, r.reviewed_by, r.reviewed_at, r.review_note = "rejected", admin.id, utcnow(), body.note
    audit.record(session, "panel_admin.request_rejected", actor_id=admin.id, actor_type="admin", entity_type="store", entity_id=r.store_id,
                 store_id=r.store_id, data={"request_id": str(r.id)})
    await session.commit()
    return {"ok": True}
