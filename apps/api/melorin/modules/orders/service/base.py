"""Order state transition, the reseller-debt error and status counters."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from melorin.core.errors import AppError
from melorin.domain.order_state import InvalidTransition, OrderStatus, assert_transition
from melorin.kernel.models.orders import Order, OrderStateTransition


S = OrderStatus


async def transition(session: AsyncSession, order: Order, to: OrderStatus, *, reason: str | None = None, actor_id=None) -> None:
    try:
        assert_transition(order.status, to)
    except InvalidTransition as e:
        raise AppError("INVALID_ORDER_STATE", f"تغییر وضعیت سفارش از {e.src} به {e.dst} مجاز نیست.", 409) from e
    session.add(OrderStateTransition(order_id=order.id, from_status=order.status, to_status=to, reason=reason, actor_id=actor_id))
    order.status = to


class ResellerDebtLimitReached(AppError):
    def __init__(self, store_id):
        super().__init__("RESELLER_DEBT_LIMIT", "فروش این فروشگاه موقتاً متوقف است. لطفاً با پشتیبانی فروشگاه تماس بگیرید.", 409)
        self.store_id = store_id


async def count_by_status(session: AsyncSession, store_id=None) -> dict[str, int]:
    q = select(Order.status, func.count()).group_by(Order.status)
    if store_id:
        q = q.where(Order.store_id == store_id)
    return {s: n for s, n in (await session.execute(q)).all()}
