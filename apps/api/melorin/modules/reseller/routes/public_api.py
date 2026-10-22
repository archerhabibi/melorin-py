"""Versioned reseller API (``/reseller-api/v1``), authenticated by API key (channel ``api``)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from melorin.core.deps import Session, StoreContext, api_access
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.stores import StoreMembership
from melorin.modules.catalog import allocation
from melorin.modules.reseller.routes.customers import adjust_customer_wallet_core
from melorin.modules.reseller.schemas import (
    CustomerOut,
    CustomerWalletAdjustment,
)

api_router = APIRouter(prefix="/reseller-api/v1", tags=["reseller-api"])


@api_router.get("/stores/{store_id}/catalog")
async def api_catalog(session: Session, ctx: StoreContext = Depends(api_access("catalog:read"))):
    rows = await allocation.sellable_products_priced(session, ctx.store)
    own = await allocation.store_bundle_prices(session, ctx.store.id)
    return [
        {
            "product_id": p.id,
            "code": p.code,
            "name": p.name,
            "price": price,
            "currency": ctx.store.currency,
            "duration_days": p.duration_days,
            "traffic_gb": p.traffic_gb,
            "bundle_prices": [{"bundle_id": gid, "price": v} for (gid, pid), v in own.items() if pid == p.id],
        }
        for p, sp, price in rows
    ]


@api_router.get("/stores/{store_id}/customers")
async def api_customers(session: Session, ctx: StoreContext = Depends(api_access("customers:read"))):
    q = (
        select(User, StoreMembership)
        .join(StoreMembership, StoreMembership.user_id == User.id)
        .where(StoreMembership.store_id == ctx.store.id, StoreMembership.role == "customer")
    )
    return [
        CustomerOut(user_id=u.id, display_name=u.display_name, email=u.email, status=m.status, joined_at=m.created_at)
        for u, m in (await session.execute(q)).all()
    ]


@api_router.get("/stores/{store_id}/orders")
async def api_orders(session: Session, ctx: StoreContext = Depends(api_access("orders:read"))):
    rows = (await session.scalars(select(Order).where(Order.store_id == ctx.store.id).order_by(Order.created_at.desc()).limit(200))).all()
    return [
        {
            "id": o.id,
            "number": o.number,
            "user_id": o.user_id,
            "product_id": o.product_id,
            "status": o.status,
            "total": o.total,
            "currency": o.currency,
            "created_at": o.created_at,
        }
        for o in rows
    ]


@api_router.post("/stores/{store_id}/customers/{customer_id}/wallet")
async def api_customer_wallet(
    customer_id: uuid.UUID,
    body: CustomerWalletAdjustment,
    session: Session,
    ctx: StoreContext = Depends(api_access("customers:wallet:write")),
):
    return await adjust_customer_wallet_core(session, ctx, customer_id, body, actor_type="api")


@api_router.get("/stores/{store_id}/reports")
async def api_reports(session: Session, ctx: StoreContext = Depends(api_access("reports:read"))):
    rows = (
        await session.execute(
            select(Order.status, func.count(), func.coalesce(func.sum(Order.total), 0))
            .where(Order.store_id == ctx.store.id)
            .group_by(Order.status)
        )
    ).all()
    return {
        "store_id": ctx.store.id,
        "currency": ctx.store.currency,
        "orders": [{"status": s, "count": n, "total": total} for s, n, total in rows],
    }
