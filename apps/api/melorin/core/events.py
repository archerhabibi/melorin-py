"""Transactional outbox. emit() writes in the caller's transaction; the worker delivers at-least-once."""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.context import correlation_id
from melorin.core.db import utcnow
from melorin.kernel.models.system import OutboxEvent

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
EVENT_CENTER_DELIVER = "eventcenter.deliver"
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


async def emit_store_notice(session, store_id, topic: str, text: str) -> None:
    """The one way to raise a store-scoped Event Center notice (T04); payments/bank_sms/provisional used private copies."""
    await emit(session, EVENT_CENTER, {"store_id": store_id, "topic": topic, "text": text})


async def emit_user_notice(
    session,
    user_id,
    store_id,
    kind: str,
    title: str,
    body: str,
    *,
    payload_dedup_key: str | None = None,
    dedup_key: str | None = None,
    delay_seconds: float = 0,
) -> None:
    """The one way to raise a customer/reseller notification (T04). Builds the ``notification.send`` payload.

    ``payload_dedup_key`` is the per-recipient key the worker stores on the Notification row (so a retry never re-sends);
    ``dedup_key`` is the outbox-level key that stops the event itself being queued twice. Callers use whichever they used before.
    """
    payload = {"user_id": user_id, "store_id": store_id, "kind": kind, "title": title, "body": body}
    if payload_dedup_key:
        payload["dedup_key"] = payload_dedup_key
    await emit(session, NOTIFY, payload, dedup_key=dedup_key, delay_seconds=delay_seconds)
