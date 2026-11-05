"""The reseller's PasarGuard admin: read-only view, and a request to change its optional "Profile & contact".

The reseller never edits the panel admin itself; the Melorin admin reviews each request (admin API ``/admin/panel-admin-requests``)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from melorin.core import audit
from melorin.core.deps import OwnerCtx, Session
from melorin.core.errors import AppError
from melorin.kernel.models.vpn import Panel, PanelAdmin, PanelAdminChangeRequest
from melorin.modules.vpn import panel_admins as svc

router = APIRouter(tags=["reseller"])


class ProfileChangeIn(BaseModel):
    changes: dict = Field(default_factory=dict)
    message: str | None = Field(default=None, max_length=500)


@router.get("/stores/{store_id}/reseller/panel-admin")
async def my_panel_admins(ctx: OwnerCtx, session: Session):
    """Where the store's accounts live: one admin per panel (no password), its status and current profile."""
    rows = (await session.scalars(select(PanelAdmin).where(PanelAdmin.store_id == ctx.store.id).order_by(PanelAdmin.created_at))).all()
    out = []
    for r in rows:
        panel = await session.get(Panel, r.panel_id)
        d = svc.public_row(r, panel=panel, store=ctx.store)
        out.append({k: d[k] for k in ("panel_name", "username", "role", "status", "profile", "profile_synced")})
    return out


@router.get("/stores/{store_id}/reseller/panel-admin/change-requests")
async def my_requests(ctx: OwnerCtx, session: Session):
    rows = (
        await session.scalars(
            select(PanelAdminChangeRequest).where(PanelAdminChangeRequest.store_id == ctx.store.id).order_by(PanelAdminChangeRequest.created_at.desc()).limit(50)
        )
    ).all()
    return [
        {"id": r.id, "changes": r.changes, "message": r.message, "status": r.status, "created_at": r.created_at, "review_note": r.review_note}
        for r in rows
    ]


@router.post("/stores/{store_id}/reseller/panel-admin/change-requests", status_code=201)
async def request_change(body: ProfileChangeIn, ctx: OwnerCtx, session: Session):
    try:
        changes = svc.clean_profile(body.changes, allowed=svc.REQUESTABLE_FIELDS)
    except svc.ProfileError as exc:
        raise AppError("PROFILE_INVALID", str(exc), 422) from exc
    if not changes:
        raise AppError("PROFILE_EMPTY", "حداقل یک فیلد برای تغییر لازم است.", 422)
    pending = await session.scalar(
        select(func.count()).select_from(PanelAdminChangeRequest).where(PanelAdminChangeRequest.store_id == ctx.store.id, PanelAdminChangeRequest.status == "pending")
    )
    if pending:
        raise AppError("REQUEST_PENDING", "یک درخواست تغییر در انتظار بررسی دارید.", 409)
    r = PanelAdminChangeRequest(store_id=ctx.store.id, requested_by=ctx.user.id, changes=changes, message=(body.message or "").strip() or None)
    session.add(r)
    await session.flush()
    audit.record(session, "panel_admin.request_created", actor_id=ctx.user.id, entity_type="store", entity_id=ctx.store.id, store_id=ctx.store.id,
                 data={"request_id": str(r.id), "fields": sorted(changes)})
    await session.commit()
    return {"id": r.id, "status": r.status}
