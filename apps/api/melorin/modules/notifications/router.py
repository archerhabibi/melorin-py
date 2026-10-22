"""Customer notifications. Store-scoped like everything else a customer sees: a notification is shown only inside the store
it was created for (``Notification.store_id``), so an account delivery of another store or bot never appears here."""

import uuid

from fastapi import APIRouter
from sqlalchemy import func, select, update

from melorin.core.db import utcnow
from melorin.core.deps import Session, StoreCtx
from melorin.core.scope import StoreScope
from melorin.kernel.models.notifications import Notification

router = APIRouter(prefix="/stores/{store_id}/notifications", tags=["notifications"])


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
async def list_notifications(ctx: StoreCtx, session: Session, unread_only: bool = False, limit: int = 50):
    cond = StoreScope.of(ctx).where(Notification)
    q = select(Notification).where(*cond).order_by(Notification.created_at.desc()).limit(min(max(limit, 1), 200))
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    unread = await session.scalar(select(func.count()).select_from(Notification).where(*cond, Notification.read_at.is_(None)))
    return {"unread": unread or 0, "items": [_out(n) for n in (await session.scalars(q)).all()]}


@router.post("/read-all")
async def read_all(ctx: StoreCtx, session: Session):
    await session.execute(
        update(Notification).where(*StoreScope.of(ctx).where(Notification), Notification.read_at.is_(None)).values(read_at=utcnow())
    )
    await session.commit()
    return {"ok": True}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: uuid.UUID, ctx: StoreCtx, session: Session):
    n = await StoreScope.of(ctx).get(session, Notification, notification_id, "اعلان")
    if n.read_at is None:
        n.read_at = utcnow()
        await session.commit()
    return _out(n)
