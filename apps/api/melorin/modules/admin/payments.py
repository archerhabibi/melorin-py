"""Admin API - payments routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import select
from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import NotFound
from melorin.modules.payments import service as payment_service
from melorin.kernel.models.payments import Payment
from melorin.modules.admin.schemas import (
    OrderAction,
    ReviewPayment,
)

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


# ----- Payments, orders, manual recovery -----
@router.get("/payments", response_model=list[dict])
async def payments(_: AdminUser, session: Session, status: str | None = Query(default=None)):
    q = select(Payment).order_by(Payment.created_at.desc()).limit(200)
    if status:
        q = q.where(Payment.status == status)
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "store_id": p.store_id,
            "amount": p.amount,
            "currency": p.currency,
            "provider": p.provider,
            "status": p.status,
            "has_receipt": bool(p.receipt_file_id),
            "created_at": p.created_at,
        }
        for p in (await session.scalars(q)).all()
    ]


@router.get("/payments/{payment_id}/receipt")
async def payment_receipt(payment_id: uuid.UUID, admin: AdminUser, session: Session):
    """Admin-only receipt download. Files stay private; every view is audited."""
    from melorin.core.storage import get_storage
    from melorin.kernel.models.system import FileObject

    p = await session.get(Payment, payment_id)
    if not p or not p.receipt_file_id:
        raise NotFound("رسید")
    fo = await session.get(FileObject, p.receipt_file_id)
    if not fo:
        raise NotFound("رسید")
    data = await get_storage().get(fo.storage_key)
    audit.record(session, "payment.receipt_viewed", actor_id=admin.id, actor_type="admin", entity_type="payment", entity_id=p.id)
    await session.commit()
    return Response(
        content=data,
        media_type=fo.content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"},
    )


@router.post("/payments/{payment_id}/review")
async def review_payment(payment_id: uuid.UUID, body: ReviewPayment, admin: AdminUser, session: Session):
    p = await session.get(Payment, payment_id)
    if not p:
        raise NotFound("پرداخت")
    if body.approve:
        await payment_service.mark_succeeded(session, p.id, actor_id=admin.id, actor_type="admin", note=body.reason)
    else:
        await payment_service.mark_failed(session, p.id, actor_id=admin.id, reason=body.reason)
    audit.record(
        session,
        "payment.reviewed",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="payment",
        entity_id=p.id,
        data={"approve": body.approve, "reason": body.reason},
    )
    await session.commit()
    return {"ok": True, "status": p.status}


@router.post("/payments/{payment_id}/refund")
async def refund_payment(payment_id: uuid.UUID, body: OrderAction, admin: AdminUser, session: Session):
    p = await payment_service.refund_payment(session, payment_id, actor_id=admin.id, reason=body.reason)
    return {"ok": True, "status": p.status, "payment_id": p.id}
