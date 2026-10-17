"""Read-only operational reports with explicit store scoping."""

from fastapi import APIRouter
from sqlalchemy import func, select

from melorin.core.deps import AdminUser, Session
from melorin.modules.orders.models import Order
from melorin.modules.payments.models import Payment
from melorin.modules.stores.models import Store

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/stores/{store_id}/sales")
async def store_sales(store_id, _: AdminUser, session: Session):
    store = await session.get(Store, store_id)
    if not store:
        return {"store_id": store_id, "currency": None, "orders": []}
    rows = (
        await session.execute(
            select(Order.status, func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
            .where(Order.store_id == store.id)
            .group_by(Order.status)
        )
    ).all()
    return {
        "store_id": store.id,
        "currency": store.currency,
        "orders": [{"status": status, "count": count, "total": total} for status, count, total in rows],
    }


@router.get("/payments")
async def payment_totals(_: AdminUser, session: Session):
    rows = (
        await session.execute(
            select(Payment.store_id, Payment.currency, func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.status == "succeeded")
            .group_by(Payment.store_id, Payment.currency)
        )
    ).all()
    return [{"store_id": sid, "currency": currency, "count": count, "amount": amount} for sid, currency, count, amount in rows]
