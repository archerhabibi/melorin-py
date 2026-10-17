import uuid

from fastapi import APIRouter
from sqlalchemy import func, select, update

from melorin.core.db import utcnow
from melorin.core.deps import CurrentUser, Session
from melorin.core.errors import NotFound
from melorin.modules.notifications.models import Notification

router = APIRouter(prefix="/me/notifications", tags=["notifications"])


def _out(n: Notification) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "store_id": n.store_id,
        "read": n.read_at is not None,
        "created_at": n.created_at,
    }


@router.get("")
async def list_notifications(user: CurrentUser, session: Session, unread_only: bool = False, limit: int = 50):
    q = select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(min(max(limit, 1), 200))
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    unread = await session.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return {"unread": unread or 0, "items": [_out(n) for n in (await session.scalars(q)).all()]}


@router.post("/read-all")
async def read_all(user: CurrentUser, session: Session):
    await session.execute(
        update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow())
    )
    await session.commit()
    return {"ok": True}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: uuid.UUID, user: CurrentUser, session: Session):
    n = await session.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise NotFound("اعلان")
    if n.read_at is None:
        n.read_at = utcnow()
        await session.commit()
    return _out(n)
