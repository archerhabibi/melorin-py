"""Transactional outbox. emit() writes in the caller's transaction; the worker delivers at-least-once."""

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.context import correlation_id
from melorin.core.db import utcnow
from melorin.core.metrics import inc
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

log = logging.getLogger("melorin.events")

# Audit T50: every topic's payload shape, as (required keys, optional keys). ``None`` for optional means free-form (the topic is
# declared but no emit() site builds a literal payload for it today). The AST test in tests/test_event_payload_schema.py checks
# every emit() call against this table, so a new or changed payload cannot ship without updating it. At runtime a mismatch is only
# logged and counted (melorin_outbox_payload_invalid_total): emit() never raises for it, so behaviour is unchanged.
PAYLOAD_SCHEMA: dict[str, tuple[frozenset[str], frozenset[str] | None]] = {
    ORDER_PAID: (frozenset({"order_id"}), frozenset({"retry_generation"})),
    ORDER_COMPLETED: (frozenset({"order_id", "store_id", "vpn_account_id"}), frozenset()),
    ORDER_DELIVERY: (frozenset({"order_id", "store_id"}), frozenset()),
    ORDER_REFUNDED: (frozenset({"order_id", "store_id"}), frozenset()),
    PROVISIONING_FAILED: (frozenset({"auto_refund", "error", "order_id", "store_id"}), frozenset()),
    PAYMENT_SUCCEEDED: (frozenset({"payment_id", "store_id"}), frozenset()),
    PAYMENT_REVIEW: (frozenset(), None),
    PAYMENT_FAILED: (frozenset({"payment_id", "store_id"}), frozenset()),
    VPN_EXPIRED: (frozenset(), None),
    VPN_NEAR_EXPIRY: (frozenset(), None),
    WALLET_CHANGED: (frozenset({"amount", "balance", "kind", "store_id", "user_id", "wallet_id"}), frozenset()),
    RESELLER_DEBT: (frozenset({"state", "store_id"}), frozenset({"balance", "limit"})),
    NOTIFY: (frozenset({"body", "kind", "title", "user_id"}), frozenset({"store_id", "dedup_key"})),
    EVENT_CENTER: (frozenset({"store_id", "text", "topic"}), frozenset()),
    EVENT_CENTER_DELIVER: (frozenset({"destination_id", "text", "topic"}), frozenset()),
    VPN_REVOKE: (frozenset({"vpn_account_id"}), frozenset()),
    VPN_RENEWAL_ROLLBACK: (frozenset({"before", "mode", "vpn_account_id"}), frozenset()),
    TICKET_UPDATED: (frozenset({"store_id", "ticket_id"}), frozenset({"message_id"})),
}


def validate_payload(topic: str, payload: dict) -> list[str]:
    """Problems with ``payload`` for ``topic`` (empty list = fine). Pure; never raises."""
    schema = PAYLOAD_SCHEMA.get(topic)
    if schema is None:
        return ["unknown_topic"]
    required, optional = schema
    keys = set(payload)
    problems = [f"missing:{k}" for k in sorted(required - keys)]
    if optional is not None:
        problems += [f"unexpected:{k}" for k in sorted(keys - required - optional)]
    return problems


async def emit(
    session: AsyncSession,
    topic: str,
    payload: dict,
    *,
    dedup_key: str | None = None,
    delay_seconds: float = 0,
) -> None:
    for problem in validate_payload(topic, payload):
        log.warning("outbox payload for %s: %s", topic, problem)
        inc("melorin_outbox_payload_invalid_total", topic=topic, problem=problem.split(":")[0])
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
