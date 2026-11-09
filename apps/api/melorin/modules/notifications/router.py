"""Customer notifications. Store-scoped like everything else a customer sees: a notification is shown only inside the store
it was created for (``Notification.store_id``), so an account delivery of another store or bot never appears here."""

import uuid

from fastapi import APIRouter
from melorin.core.db import utcnow
from melorin.core.deps import Session, StoreCtx
from melorin.core.scope import StoreScope
from melorin.kernel.models.notifications import Notification
from melorin.modules.notifications import queries

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
    unread, items = await queries.list_for_store(session, StoreScope.of(ctx).where(Notification), unread_only=unread_only, limit=limit)
    return {"unread": unread, "items": [_out(n) for n in items]}


@router.post("/read-all")
async def read_all(ctx: StoreCtx, session: Session):
    await queries.mark_all_read(session, StoreScope.of(ctx).where(Notification))
    await session.commit()
    return {"ok": True}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: uuid.UUID, ctx: StoreCtx, session: Session):
    n = await StoreScope.of(ctx).get(session, Notification, notification_id, "اعلان")
    if n.read_at is None:
        n.read_at = utcnow()
        await session.commit()
    return _out(n)
