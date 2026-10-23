"""Admin API - manual tasks: the checklist of things only a human can do outside Melorin when a reseller registers."""

import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import NotFound
from melorin.kernel.models.stores import AdminTask, ResellerApplication
from melorin.modules.reseller.onboarding import task_out

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/manual-tasks")
async def list_tasks(_: AdminUser, session: Session, status: str = "open"):
    q = select(AdminTask, ResellerApplication).join(ResellerApplication, ResellerApplication.id == AdminTask.application_id, isouter=True)
    if status in ("open", "done"):
        q = q.where(AdminTask.status == status)
    rows = (await session.execute(q.order_by(AdminTask.created_at.desc()).limit(500))).all()
    open_count = await session.scalar(select(func.count()).select_from(AdminTask).where(AdminTask.status == "open"))
    return {"open": int(open_count or 0), "items": [task_out(t, a) for t, a in rows]}


async def _set(task_id: uuid.UUID, done: bool, admin, session) -> dict:
    t = await session.get(AdminTask, task_id, with_for_update=True)
    if not t:
        raise NotFound("کار دستی")
    t.status, t.done_by, t.done_at = ("done", admin.id, utcnow()) if done else ("open", None, None)
    audit.record(
        session,
        "admin.manual_task_done" if done else "admin.manual_task_reopened",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="admin_task",
        entity_id=t.id,
        data={"kind": t.kind},
    )
    await session.commit()
    return task_out(t, await session.get(ResellerApplication, t.application_id) if t.application_id else None)


@router.post("/manual-tasks/{task_id}/done")
async def mark_done(task_id: uuid.UUID, admin: AdminUser, session: Session):
    return await _set(task_id, True, admin, session)


@router.post("/manual-tasks/{task_id}/reopen")
async def reopen(task_id: uuid.UUID, admin: AdminUser, session: Session):
    return await _set(task_id, False, admin, session)
