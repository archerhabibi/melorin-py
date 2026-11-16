"""Admin API - central person profile, link conflicts and consolidation approval (docs/25 §9).

Permission areas (``domain/admin_access.py``): reading and conflict review need ``customers``; approving a consolidation moves money, so it
needs ``payments`` write. Support/viewer roles never get there.
"""

import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from melorin.core.db import utcnow
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.domain import account_linking as rules
from melorin.kernel.models.identity import User
from melorin.kernel.models.person import AccountConsolidationOperation, AccountLinkOperation
from melorin.modules.identity.account_linking import audit, consolidation, linking, persons, queries

router = APIRouter(prefix="/admin", tags=["admin"])


class ConflictReviewIn(BaseModel):
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=3, max_length=500)  # always recorded: who decided, and why
    keep_telegram: Literal["target", "source"] | None = None


class ApproveIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.get("/identity/persons/by-user/{user_id}")
async def person_of_user(user_id: uuid.UUID, _: AdminUser, session: Session):
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("کاربر")
    person = await persons.ensure_person(session, user)
    await session.commit()
    return await queries.person_detail(session, person.id)


@router.get("/identity/persons/{person_id}")
async def person_detail(person_id: uuid.UUID, _: AdminUser, session: Session):
    return await queries.person_detail(session, person_id)


@router.get("/identity/persons/{person_id}/accounts")
async def person_accounts(person_id: uuid.UUID, _: AdminUser, session: Session):
    return (await queries.person_detail(session, person_id))["accounts"]


@router.get("/identity/persons/{person_id}/links")
async def person_links(person_id: uuid.UUID, _: AdminUser, session: Session):
    d = await queries.person_detail(session, person_id)
    return {"identities": d["identities"], "operations": d["operations"], "audit": d["audit"]}


@router.get("/identity/link-conflicts")
async def link_conflicts(_: AdminUser, session: Session, status: str = "conflict"):
    q = select(AccountLinkOperation).order_by(AccountLinkOperation.created_at).limit(200)
    if status != "all":
        q = q.where(AccountLinkOperation.status == status)
    rows = (await session.scalars(q)).all()
    return [
        {**queries.operation_card(o), "person_id": o.person_id, "conflict_person_id": o.conflict_person_id, "account_id": o.user_id}
        for o in rows
    ]


@router.post("/identity/link-conflicts/{operation_id}/review")
async def review_conflict(operation_id: uuid.UUID, body: ConflictReviewIn, admin: AdminUser, session: Session):
    op = await session.get(AccountLinkOperation, operation_id, with_for_update=True)
    if op is None:
        raise NotFound("عملیات اتصال")
    if op.status != rules.OpStatus.CONFLICT or op.conflict_person_id is None:
        raise AppError("OPERATION_NOT_REVIEWABLE", "این درخواست در وضعیت بررسی نیست.", 409)
    if body.action == "reject":
        op.status = str(rules.OpStatus.REJECTED)
        audit.log(
            session,
            "conflict_rejected",
            person_id=op.person_id,
            actor_id=admin.id,
            actor_type="admin",
            operation_id=op.id,
            reason=body.reason,
        )
        await session.commit()
        return {"status": op.status}
    first, second = sorted({op.person_id, op.conflict_person_id}, key=str)
    locked = {first: await persons.lock_person(session, first), second: await persons.lock_person(session, second)}
    target, source = locked[op.person_id], locked[op.conflict_person_id]
    if source.status == "merged" or target.status != "active" or source.status != "active":
        raise AppError("OPERATION_STALE", "وضعیت پروفایل‌ها تغییر کرده است.", 409)
    summary = await linking.link_persons(
        session, target, source, actor_id=admin.id, actor_type="admin", operation=op, keep_telegram=body.keep_telegram
    )
    linking.add_evidence(session, op, rules.Evidence.ADMIN_REVIEW, subject=f"admin:{admin.id}", data={"reason": body.reason})
    op.status, op.completed_at = str(rules.OpStatus.CONFIRMED), utcnow()
    audit.log(
        session, "conflict_approved", person_id=target.id, actor_id=admin.id, actor_type="admin", operation_id=op.id, reason=body.reason
    )
    await session.commit()
    return summary


@router.get("/identity/consolidations")
async def list_consolidations(_: AdminUser, session: Session, status: str = "pending_approval"):
    q = select(AccountConsolidationOperation).order_by(AccountConsolidationOperation.created_at).limit(200)
    if status != "all":
        q = q.where(AccountConsolidationOperation.status == status)
    return [{**queries.consolidation_card(c), "person_id": c.target_person_id} for c in (await session.scalars(q)).all()]


@router.get("/identity/consolidations/{consolidation_id}")
async def get_consolidation(consolidation_id: uuid.UUID, _: AdminUser, session: Session):
    c = await session.get(AccountConsolidationOperation, consolidation_id)
    if c is None:
        raise NotFound("عملیات یکپارچه‌سازی")
    return {**queries.consolidation_card(c), "person_id": c.target_person_id, "approved_by": c.approved_by}


@router.post("/identity/consolidations/{consolidation_id}/approve")
async def approve_consolidation(consolidation_id: uuid.UUID, body: ApproveIn, admin: AdminUser, session: Session):
    c = await session.get(AccountConsolidationOperation, consolidation_id)
    if c is None:
        raise NotFound("عملیات یکپارچه‌سازی")
    audit.log(
        session,
        "consolidation_approved",
        person_id=c.target_person_id,
        actor_id=admin.id,
        actor_type="admin",
        operation_id=c.id,
        reason=body.reason,
    )
    done = await consolidation.execute(session, c, approver_id=admin.id, actor_type="admin")
    return queries.consolidation_card(done)
