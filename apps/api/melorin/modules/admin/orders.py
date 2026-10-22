"""Admin API - orders routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter, Query
from sqlalchemy import select
from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.catalog import Product
from melorin.modules.orders import service as order_service
from melorin.kernel.models.orders import Order
from melorin.kernel.models.vpn import Server, VpnAccount
from melorin.modules.admin.schemas import (
    AttachExistingAccount,
    OrderAction,
)

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


@router.get("/orders", response_model=list[dict])
async def orders(
    _: AdminUser, session: Session, status: str | None = Query(default=None), store_id: uuid.UUID | None = Query(default=None)
):
    q = select(Order).order_by(Order.created_at.desc()).limit(200)
    if status:
        q = q.where(Order.status == status)
    if store_id:
        q = q.where(Order.store_id == store_id)
    return [
        {
            "id": o.id,
            "number": o.number,
            "user_id": o.user_id,
            "store_id": o.store_id,
            "status": o.status,
            "total": o.total,
            "currency": o.currency,
            "needs_review": o.needs_review,
            "created_at": o.created_at,
        }
        for o in (await session.scalars(q)).all()
    ]


@router.post("/orders/{order_id}/retry")
async def retry_order(order_id: uuid.UUID, admin: AdminUser, session: Session):
    o = await session.get(Order, order_id)
    if not o:
        raise NotFound("سفارش")
    await order_service.admin_retry(session, o, admin)
    return {"ok": True}


@router.post("/orders/{order_id}/manual-review")
async def review_order(order_id: uuid.UUID, body: OrderAction, admin: AdminUser, session: Session):
    o = await session.get(Order, order_id)
    if not o:
        raise NotFound("سفارش")
    await order_service.admin_mark_review(session, o, admin, body.reason)
    return {"ok": True}


@router.post("/orders/{order_id}/refund")
async def refund_order(order_id: uuid.UUID, body: OrderAction, admin: AdminUser, session: Session):
    o = await session.get(Order, order_id)
    if not o:
        raise NotFound("سفارش")
    await order_service.refund(session, o, admin, body.reason)
    return {"ok": True}


@router.post("/orders/{order_id}/attach-account")
async def attach_account(order_id: uuid.UUID, body: AttachExistingAccount, admin: AdminUser, session: Session):
    o = await session.get(Order, order_id, with_for_update=True)
    s = await session.get(Server, body.server_id)
    if not o or not s:
        raise NotFound("سفارش یا سرور")
    if o.status not in ("provisioning_failed", "manual_review"):
        raise AppError("INVALID_ORDER_STATE", "سفارش در وضعیت بررسی دستی نیست.", 409)
    product = await session.get(Product, o.product_id)
    if not product:
        raise NotFound("محصول")
    a = VpnAccount(
        username=body.username,
        user_id=o.user_id,
        store_id=o.store_id,
        order_id=o.id,
        product_id=o.product_id,
        server_id=s.id,
        panel_id=s.panel_id,
        panel_ref=body.panel_ref,
        subscription_url=body.subscription_url,
        status="active",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").UTC)
        + __import__("datetime").timedelta(days=product.duration_days),
        traffic_limit_bytes=product.traffic_gb * 1024**3,
    )
    session.add(a)
    await session.flush()
    o.vpn_account_id, o.status, o.needs_review = a.id, "completed", False
    audit.record(
        session,
        "provisioning.account_attached",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="vpn_account",
        entity_id=a.id,
        store_id=o.store_id,
        data={"reason": body.reason},
    )
    await session.commit()
    return {"ok": True, "vpn_account_id": a.id}
