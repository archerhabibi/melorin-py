"""Async outbox worker. V1 uses PostgreSQL polling and row locks; Redis/ARQ is a swappable boundary."""

import datetime as dt
import logging
import uuid

from sqlalchemy import select

from melorin.core import events
from melorin.core.config import get_settings
from melorin.core.db import session_factory, utcnow
from melorin.core.metrics import inc
from melorin.core.crypto import decrypt
from melorin import models  # noqa: F401, register all SQLAlchemy mappers before worker sessions
from melorin.kernel.models.identity import User
from melorin.kernel.models.notifications import Notification
from melorin.kernel.models.orders import Order
from melorin.kernel.models.system import OutboxEvent
from melorin.modules.orders import provisioning as vpn
from melorin.modules.vpn.adapters.registry import build_adapter_for
from melorin.kernel.models.vpn import Panel, VpnAccount

log = logging.getLogger("melorin.worker")


async def claim_batch(session, n=20):
    # Recover workers killed after claiming a row. A claim is leased, not permanent.
    lease_cutoff = utcnow() - dt.timedelta(minutes=10)
    await session.execute(
        OutboxEvent.__table__.update()
        .where(OutboxEvent.status == "processing", OutboxEvent.locked_at < lease_cutoff)
        .values(status="pending", locked_at=None, available_at=utcnow())
    )
    q = (
        select(OutboxEvent)
        .where(OutboxEvent.status == "pending", OutboxEvent.available_at <= utcnow())
        .order_by(OutboxEvent.created_at)
        .limit(n)
        .with_for_update(skip_locked=True)
    )
    rows = (await session.scalars(q)).all()
    for e in rows:
        e.status, e.locked_at = "processing", utcnow()
    await session.commit()
    return rows


async def _webhook(session, event_type: str, payload: dict, event_id: str):
    """Best-effort enqueue only. Delivery is separate, signed and retried by the webhook worker."""
    store_id = payload.get("store_id")
    if not store_id:
        return
    try:
        from melorin.modules.webhooks.service import enqueue_event

        await enqueue_event(session, store_id=uuid.UUID(str(store_id)), event_type=event_type, payload=payload, event_id=event_id)
    except Exception:
        log.exception("webhook enqueue failed event=%s", event_id)


def _oid(p: dict, key: str = "order_id") -> uuid.UUID:
    return uuid.UUID(str(p[key]))


# One small handler per outbox topic. Handlers resolve their collaborators (``vpn``, ``_webhook``, ``_notify`` ...) from
# this module's globals at call time, so tests can still patch them. Behaviour per topic is unchanged from the former
# ``elif`` chain: same calls, same order, same webhook event names and idempotency keys.
async def _on_order_paid(session, p: dict):
    await vpn.provision_order(session, _oid(p))


async def _on_provisioning_failed(session, p: dict):
    await _notify_admins_provisioning_failed(session, p)
    await _webhook(session, "order.provisioning_failed", p, f"order.provisioning_failed:{p.get('order_id')}")


async def _on_order_completed(session, p: dict):
    from melorin.modules.referral.service import on_order_completed

    await on_order_completed(session, _oid(p))
    await _webhook(session, "order.completed", p, f"order.completed:{p.get('order_id')}")


async def _on_order_delivery(session, p: dict):
    from melorin.modules.orders.delivery import deliver_order

    await deliver_order(session, _oid(p))


async def _on_order_refunded(session, p: dict):
    from melorin.modules.referral.service import on_order_refunded

    await on_order_refunded(session, _oid(p))
    await _webhook(session, "order.refunded", p, f"order.refunded:{p.get('order_id')}")


async def _on_vpn_revoke(session, p: dict):
    await revoke_account(session, _oid(p, "vpn_account_id"))


async def _on_vpn_renewal_rollback(session, p: dict):
    await rollback_renewal(session, p)


async def _on_notify(session, p: dict):
    kind = p.get("kind")
    await _notify(session, p, p.get("kind", "general"), p.get("title", "Melorin"), p.get("body", ""))
    if p.get("store_id") and kind in ("vpn_expired", "vpn_near_expiry"):
        await _webhook(
            session,
            "vpn_account.expired" if kind == "vpn_expired" else "vpn_account.near_expiry",
            p,
            f"{kind}:{p.get('dedup_key') or p.get('user_id')}",
        )


async def _on_event_center(session, p: dict):
    await _event_center(session, p)


async def _on_event_center_deliver(session, p: dict):
    from melorin.modules.eventcenter import service as event_center

    await event_center.deliver(session, p)


def _webhook_only(event_name: str, key):
    """Handler for topics that only fan out to reseller webhooks; ``key(p)`` builds the idempotent event id."""

    async def handler(session, p: dict):
        await _webhook(session, event_name, p, f"{event_name}:{key(p)}")

    return handler


_TOPIC_HANDLERS = {
    events.ORDER_PAID: _on_order_paid,
    events.PROVISIONING_FAILED: _on_provisioning_failed,
    events.ORDER_COMPLETED: _on_order_completed,
    events.ORDER_DELIVERY: _on_order_delivery,
    events.ORDER_REFUNDED: _on_order_refunded,
    events.VPN_REVOKE: _on_vpn_revoke,
    events.VPN_RENEWAL_ROLLBACK: _on_vpn_renewal_rollback,
    events.NOTIFY: _on_notify,
    events.EVENT_CENTER: _on_event_center,
    events.EVENT_CENTER_DELIVER: _on_event_center_deliver,
    events.TICKET_UPDATED: _on_event_center,
    events.PAYMENT_SUCCEEDED: _webhook_only("payment.succeeded", lambda p: p.get("payment_id")),
    events.PAYMENT_FAILED: _webhook_only("payment.failed", lambda p: p.get("payment_id")),
    events.WALLET_CHANGED: _webhook_only("wallet.changed", lambda p: f"{p.get('wallet_id')}:{p.get('amount')}:{p.get('balance')}"),
    events.RESELLER_DEBT: _webhook_only("reseller.debt", lambda p: f"{p.get('store_id')}:{p.get('state')}:{p.get('balance')}"),
}


OUTBOX_MAX_BACKOFF = 1800  # seconds
OUTBOX_MAX_RETRY_AFTER = 3600  # a Telegram flood-wait longer than this is not waited out in one step


def _retry_delay(attempts: int, exc: Exception) -> int:
    """Seconds before the next outbox attempt: exponential backoff, but never sooner than Telegram's ``retry_after``.

    A 429 answer tells exactly how long the bot must wait; retrying earlier only extends the flood-wait.
    """
    delay = min(OUTBOX_MAX_BACKOFF, 2 ** min(attempts, 8))
    retry_after = getattr(exc, "retry_after", None)
    if isinstance(retry_after, int) and retry_after > 0:
        delay = max(delay, min(OUTBOX_MAX_RETRY_AFTER, retry_after + 1))
    return delay


async def process_event(e: OutboxEvent):
    event_id = e.id
    async with session_factory()() as session:
        try:
            # claim_batch commits before returning, so never mutate its
            # detached ORM instance. Re-load the row in this session.
            e = await session.get(OutboxEvent, event_id, with_for_update=True)
            if e is None or e.status != "processing":
                return
            handler = _TOPIC_HANDLERS.get(e.topic)
            if handler is not None:  # unknown topics are acknowledged without work, as before
                await handler(session, e.payload or {})
            if e.topic != events.EVENT_CENTER_DELIVER:  # Telegram fan-out: best-effort, inside a SAVEPOINT, never fails the event
                from melorin.modules.eventcenter import rules as event_center_rules

                await event_center_rules.tap(session, e)
            e.status, e.processed_at, e.last_error = "processed", utcnow(), None
            await session.commit()
            inc("melorin_outbox_events_total", topic=e.topic, result="processed")
        except Exception as ex:
            log.exception("outbox failed %s", event_id)
            failed = await session.get(OutboxEvent, event_id, with_for_update=True)
            if failed is not None and failed.status == "processing":
                failed.status, failed.attempts, failed.last_error = "pending", failed.attempts + 1, str(ex)
                failed.available_at = utcnow() + dt.timedelta(seconds=_retry_delay(failed.attempts, ex))
                from melorin.modules.eventcenter import rules as event_center_rules

                await event_center_rules.report_outbox_failure(session, failed)
                await session.commit()
                inc("melorin_outbox_events_total", topic=failed.topic, result="retry")


async def _notify(session, p: dict, kind: str, title: str, body: str = ""):
    if not p.get("user_id"):
        return
    user_id = uuid.UUID(str(p["user_id"]))
    dedup_key = p.get("dedup_key")
    n = await session.scalar(select(Notification).where(Notification.dedup_key == dedup_key)) if dedup_key else None
    if n and n.telegram_status == "sent":
        return
    if n is None:
        n = Notification(
            user_id=user_id,
            store_id=uuid.UUID(str(p["store_id"])) if p.get("store_id") else None,
            kind=kind,
            title=title,
            body=body,
            dedup_key=dedup_key,
        )
        session.add(n)
        await session.flush()
    from melorin.kernel.models.identity import Identity

    identity = await session.scalar(select(Identity).where(Identity.user_id == user_id, Identity.provider == "telegram"))
    if not identity:
        n.telegram_status = "skipped"
        return
    from melorin.kernel.models.stores import Store

    store = await session.get(Store, n.store_id) if n.store_id else None
    token = decrypt(store.bot_token_enc) if store and store.bot_token_enc else get_settings().main_bot_token
    if not token:
        n.telegram_status = "skipped"
        return
    try:
        from melorin.channels.telegram import TelegramChannel

        await TelegramChannel(
            token, get_settings().store_web_url, "reseller" if store and store.kind == "reseller" else "main"
        ).send_message(identity.subject, f"{title}\n{body}")
        n.telegram_status = "sent"
        inc("melorin_notifications_total", channel="telegram", result="sent")
    except Exception:
        n.telegram_status = "failed"
        inc("melorin_notifications_total", channel="telegram", result="failed")
        raise


async def _notify_admins_provisioning_failed(session, p: dict):
    """Telegram alert to every active super admin that provisioning failed.

    The outcome line is read from the order at send time (the event is emitted
    with a short delay so the auto-refund has finished by then). Each admin has
    their own dedup key, so an outbox retry never re-sends to admins who already
    received the message.
    """
    from melorin.domain.order_state import OrderStatus

    order_id = uuid.UUID(str(p["order_id"]))
    order = await session.get(Order, order_id)
    number = order.number if order else str(order_id)[:8]
    if order and order.status == OrderStatus.REFUNDED:
        outcome = "✅ مبلغ به‌صورت خودکار به کیف پول مشتری برگشت داده شد."
    elif order and order.status in (OrderStatus.PROVISIONING_FAILED, OrderStatus.REFUND_PENDING):
        outcome = "❌ بازگشت خودکار وجه انجام نشد؛ لطفاً سفارش را دستی بررسی کنید."
    else:
        outcome = ""
    error = (p.get("error") or "نامشخص")[:300]
    title = "⚠️ ساخت اکانت ناموفق بود"
    body = f"سفارش: {number}\nخطا: {error}"
    if outcome:
        body += f"\n{outcome}"

    admin_ids = (await session.scalars(select(User.id).where(User.is_super_admin.is_(True), User.is_active.is_(True)))).all()
    errors: list[Exception] = []
    for admin_id in admin_ids:
        try:
            await _notify(
                session,
                {"user_id": admin_id, "dedup_key": f"prov_fail_admin:{order_id}:{admin_id}"},
                "provisioning_failed",
                title,
                body,
            )
        except Exception as ex:  # one unreachable admin must not block the others
            errors.append(ex)
    if errors:
        raise errors[0]  # outbox retries; admins already marked "sent" are skipped via dedup


async def _event_center(session, p: dict):
    # Telegram delivery is queued by eventcenter.rules.tap() right after this handler; here we only keep the log line.
    log.info("event-center store=%s topic=%s text=%s", p.get("store_id"), p.get("topic"), p.get("text"))


async def revoke_account(session, account_id):
    a = await session.get(VpnAccount, account_id)
    if not a or not a.panel_id:
        return
    panel = await session.get(Panel, a.panel_id)
    await build_adapter_for(panel, a).revoke_account(a.username)
    a.status = "revoked"
    await session.commit()


async def rollback_renewal(session, payload):
    account = await session.get(VpnAccount, uuid.UUID(str(payload["vpn_account_id"])), with_for_update=True)
    if not account or not account.panel_id:
        return
    before = payload.get("before") or {}
    panel = await session.get(Panel, account.panel_id)
    pa = await build_adapter_for(panel, account).extend_account(
        account.username,
        expire_at=dt.datetime.fromisoformat(before["expires_at"]) if before.get("expires_at") else None,
        traffic_bytes=int(before.get("traffic_limit_bytes") or 0),
    )
    account.expires_at, account.traffic_limit_bytes = pa.expire_at, pa.traffic_limit_bytes
    await session.commit()


async def claim_webhook_batch(session, n=20):
    from melorin.kernel.models.webhooks import WebhookDelivery

    lease_cutoff = utcnow() - dt.timedelta(minutes=10)
    await session.execute(
        WebhookDelivery.__table__.update()
        .where(WebhookDelivery.status == "delivering", WebhookDelivery.updated_at < lease_cutoff)
        .values(status="pending", next_attempt_at=utcnow())
    )
    q = (
        select(WebhookDelivery)
        .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= utcnow())
        .order_by(WebhookDelivery.created_at)
        .limit(n)
        .with_for_update(skip_locked=True)
    )
    rows = (await session.scalars(q)).all()
    for d in rows:
        d.status = "delivering"
    await session.commit()
    return rows


async def process_webhook(d):
    async with session_factory()() as session:
        try:
            from melorin.modules.webhooks.service import deliver_one

            await deliver_one(session, d.id)
        except Exception:
            log.exception("webhook delivery failed id=%s", d.id)
