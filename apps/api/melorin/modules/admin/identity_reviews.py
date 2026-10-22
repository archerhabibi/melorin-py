"""Admin API - identity reviews routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.identity import IdentityLinkReview, User
from melorin.kernel.models.orders import Order

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


# ----- verified-email identity conflicts -----
REVIEW_STATUSES = {"open", "linked", "dismissed"}


class ReviewNoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def _review_user_card(u: User | None, orders: dict) -> dict | None:
    if u is None:
        return None
    return {
        "id": u.id,
        "display_name": u.display_name,
        "email": u.email,
        "is_guest": bool(u.is_guest),
        "is_active": bool(u.is_active),
        "created_at": u.created_at,
        "providers": sorted({i.provider for i in u.identities}),
        "orders": int(orders.get(u.id, 0)),
    }


@router.get("/identity-link-reviews")
async def identity_link_reviews(_: AdminUser, session: Session, status: str = "open"):
    """Identity-link conflicts. ``status`` = open | linked | dismissed | all. Each row carries a short card of the
    account that triggered it and of the accounts it collided with, so the admin can decide without extra lookups."""
    if status != "all" and status not in REVIEW_STATUSES:
        raise AppError("INVALID_STATUS", "وضعیت نامعتبر است.", 422)
    q = select(IdentityLinkReview).order_by(IdentityLinkReview.created_at)
    if status != "all":
        q = q.where(IdentityLinkReview.status == status)
    rows = (await session.scalars(q)).all()

    def _uuid(v):
        try:
            return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
        except (ValueError, TypeError):
            return None

    wanted: set[uuid.UUID] = set()
    for r in rows:
        wanted.add(r.source_user_id)
        wanted.update(x for x in (_uuid(c) for c in (r.candidate_user_ids or [])) if x)
    users: dict = {}
    orders: dict = {}
    if wanted:
        users = {u.id: u for u in (await session.scalars(select(User).where(User.id.in_(wanted)))).all()}
        orders = dict(
            (await session.execute(select(Order.user_id, func.count()).where(Order.user_id.in_(wanted)).group_by(Order.user_id))).all()
        )
    out = []
    for r in rows:
        cand_ids = [x for x in (_uuid(c) for c in (r.candidate_user_ids or [])) if x]
        out.append(
            {
                "id": r.id,
                "email": r.email,
                "source_user_id": r.source_user_id,
                "candidate_user_ids": r.candidate_user_ids,
                "provider": r.provider,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at,
                "resolved_at": r.updated_at if r.status != "open" else None,
                "resolved_by": r.resolved_by,
                "resolution_note": r.resolution_note,
                "source_user": _review_user_card(users.get(r.source_user_id), orders),
                "candidates": [c for c in (_review_user_card(users.get(i), orders) for i in cand_ids) if c],
            }
        )
    return out


@router.post("/identity-link-reviews/{review_id}/dismiss")
async def dismiss_identity_review(review_id: uuid.UUID, admin: AdminUser, session: Session, body: ReviewNoteIn | None = None):
    r = await session.get(IdentityLinkReview, review_id, with_for_update=True)
    if not r or r.status != "open":
        raise NotFound("درخواست اتصال هویت")
    note = (body.note or "").strip()[:500] if body else ""
    r.status = "dismissed"
    r.resolved_by = admin.id
    r.resolution_note = note or None
    audit.record(
        session,
        "identity_link_review.dismissed",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="identity_link_review",
        entity_id=r.id,
        data={"email": r.email, "note": note or None},
    )
    await session.commit()
    return {"ok": True}


@router.post("/identity-link-reviews/{review_id}/reopen")
async def reopen_identity_review(review_id: uuid.UUID, admin: AdminUser, session: Session):
    """Undo a dismissal (mistaken click): the item goes back to the open queue."""
    r = await session.get(IdentityLinkReview, review_id, with_for_update=True)
    if not r or r.status != "dismissed":
        raise NotFound("درخواست اتصال هویت")
    r.status = "open"
    r.resolved_by = None
    r.resolution_note = None
    audit.record(
        session,
        "identity_link_review.reopened",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="identity_link_review",
        entity_id=r.id,
        data={"email": r.email},
    )
    await session.commit()
    return {"ok": True}
