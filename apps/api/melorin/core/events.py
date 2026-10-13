"""Transactional outbox. emit() writes in the caller's transaction; the worker delivers at-least-once."""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.context import correlation_id
from melorin.core.db import utcnow
from melorin.modules.system.models import OutboxEvent

# Topics
ORDER_PAID = "order.paid"
ORDER_COMPLETED = "order.completed"
ORDER_DELIVERY = "order.delivery"
ORDER_REFUNDED = "order.refunded"
PROVISIONING_FAILED = "provisioning.failed"
PAYMENT_SUCCEEDED = "payment.succeeded"
PAYMENT_REVIEW = "payment.awaiting_review"
PAYMENT_FAILED = "payment.failed"
VPN_EXPIRED = "vpn.expired"
VPN_NEAR_EXPIRY = "vpn.near_expiry"
WALLET_CHANGED = "wallet.changed"
RESELLER_DEBT = "reseller.debt"
NOTIFY = "notification.send"
EVENT_CENTER = "eventcenter.send"
VPN_REVOKE = "vpn.revoke"
VPN_RENEWAL_ROLLBACK = "vpn.renewal_rollback"
TICKET_UPDATED = "ticket.updated"


async def emit(
    session: AsyncSession,
    topic: str,
    payload: dict,
    *,
    dedup_key: str | None = None,
    delay_seconds: float = 0,
) -> None:
    if dedup_key:
        exists = await session.scalar(select(OutboxEvent.id).where(OutboxEvent.dedup_key == dedup_key))
        if exists:
            return
    session.add(
        OutboxEvent(
            topic=topic,
            payload=_jsonable(payload),
            dedup_key=dedup_key,
            available_at=utcnow() + dt.timedelta(seconds=delay_seconds),
            correlation_id=correlation_id.get(),
        )
    )


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, str | int | float | bool) or v is None:
        return v
    return str(v)
