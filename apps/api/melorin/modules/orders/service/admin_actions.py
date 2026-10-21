"""Admin/operator actions on an order: cancel, retry provisioning, mark for review."""

from sqlalchemy.ext.asyncio import AsyncSession
from melorin.core import audit, events
from melorin.core.errors import AppError
from melorin.domain.order_state import RETRYABLE
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.modules.orders.service.base import S, transition


async def cancel(session: AsyncSession, order: Order, actor_id) -> None:
    await transition(session, order, S.CANCELLED, actor_id=actor_id)
    audit.record(session, "order.cancelled", actor_id=actor_id, entity_type="order", entity_id=order.id, store_id=order.store_id)
    await session.commit()


async def admin_retry(session: AsyncSession, order: Order, admin: User) -> None:
    if order.status not in RETRYABLE:
        raise AppError("INVALID_ORDER_STATE", "این سفارش قابل تلاش مجدد نیست.", 409)
    await transition(session, order, S.PROCESSING, reason="admin retry", actor_id=admin.id)
    retry_generation = order.provisioning_attempts + 1
    order.provisioning_attempts = retry_generation
    order.needs_review = False
    await events.emit(
        session,
        events.ORDER_PAID,
        {"order_id": order.id, "retry_generation": retry_generation},
        dedup_key=f"order_paid_retry:{order.id}:{retry_generation}",
    )
    audit.record(
        session,
        "provisioning.retry",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="order",
        entity_id=order.id,
        store_id=order.store_id,
    )
    await session.commit()


async def admin_mark_review(session: AsyncSession, order: Order, admin: User, note: str | None) -> None:
    await transition(session, order, S.MANUAL_REVIEW, reason=note, actor_id=admin.id)
    order.needs_review = True
    audit.record(session, "order.manual_review", actor_id=admin.id, actor_type="admin", entity_type="order", entity_id=order.id)
    await session.commit()
