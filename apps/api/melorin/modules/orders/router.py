import uuid

from fastapi import APIRouter, Header
from sqlalchemy import select

from melorin.core.deps import Session, StoreCtx
from melorin.core.scope import StoreScope
from melorin.modules.orders import service
from melorin.kernel.models.orders import Order
from melorin.modules.orders.schemas import CreateOrder, OrderOut

router = APIRouter(tags=["orders"])


def out(o: Order) -> OrderOut:
    return OrderOut(
        id=o.id,
        number=o.number,
        store_id=o.store_id,
        user_id=o.user_id,
        product_id=o.product_id,
        kind=o.kind,
        status=o.status,
        payment_method=o.payment_method,
        channel=o.channel,
        currency=o.currency,
        unit_price=o.unit_price,
        discount=o.discount,
        total=o.total,
        coupon_code=o.coupon_code,
        product_snapshot=o.product_snapshot,
        vpn_account_id=o.vpn_account_id,
        bundle_id=o.bundle_id,
        selected_panel_id=o.selected_panel_id,
        requested_account_name=o.requested_account_name,
        needs_review=o.needs_review,
        created_at=o.created_at,
        paid_at=o.paid_at,
        completed_at=o.completed_at,
    )


@router.post("/stores/{store_id}/orders", response_model=OrderOut, status_code=201)
async def create_order(
    body: CreateOrder,
    ctx: StoreCtx,
    session: Session,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=100),
):
    o = await service.create_order(
        session,
        ctx,
        product_id=body.product_id,
        payment_method=body.payment_method,
        idempotency_key=idempotency_key,
        coupon_code=body.coupon_code,
        kind=body.kind,
        vpn_account_id=body.vpn_account_id,
        bundle_id=body.bundle_id,
        selected_panel_id=body.selected_panel_id,
        account_name=body.account_name,
        channel="web",
    )
    return out(o)


@router.post("/stores/{store_id}/test-account", response_model=OrderOut, status_code=201)
async def test_account(ctx: StoreCtx, session: Session):
    return out(await service.create_test_order(session, ctx, "web"))


@router.get("/stores/{store_id}/orders", response_model=list[OrderOut])
async def list_orders(ctx: StoreCtx, session: Session):
    """Only the caller's own orders of THIS store."""
    rows = (await session.scalars(select(Order).where(*StoreScope.of(ctx).where(Order)).order_by(Order.created_at.desc()).limit(100))).all()
    return [out(o) for o in rows]


@router.get("/stores/{store_id}/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, ctx: StoreCtx, session: Session):
    """One of the caller's own orders of THIS store (another user's or another store's order: 404). Admins use /admin/orders."""
    return out(await StoreScope.of(ctx).get(session, Order, order_id, "سفارش"))
