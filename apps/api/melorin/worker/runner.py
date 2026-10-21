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
from melorin.modules.identity.models import User
from melorin.modules.notifications.models import Notification
from melorin.modules.orders.models import Order
from melorin.modules.system.models import OutboxEvent
from melorin.modules.vpn import service as vpn
from melorin.modules.vpn.adapters.registry import build_adapter
from melorin.modules.vpn.models import Panel, VpnAccount

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


async def process_event(e: OutboxEvent):
    event_id = e.id
    async with session_factory()() as session:
        try:
            # claim_batch commits before returning, so never mutate its
            # detached ORM instance. Re-load the row in this session.
            e = await session.get(OutboxEvent, event_id, with_for_update=True)
            if e is None or e.status != "processing":
                return
            p = e.payload or {}
            if e.topic == events.ORDER_PAID:
                await vpn.provision_order(session, uuid.UUID(str(p["order_id"])))
            elif e.topic == events.PROVISIONING_FAILED:
                await _notify_admins_provisioning_failed(session, p)
                await _webhook(session, "order.provisioning_failed", p, f"order.provisioning_failed:{p.get('order_id')}")
            elif e.topic == events.ORDER_COMPLETED:
                from melorin.modules.referral.service import on_order_completed

                await on_order_completed(session, uuid.UUID(str(p["order_id"])))
                await _webhook(session, "order.completed", p, f"order.completed:{p.get('order_id')}")
            elif e.topic == events.ORDER_DELIVERY:
                from melorin.modules.orders.delivery import deliver_order

                await deliver_order(session, uuid.UUID(str(p["order_id"])))
            elif e.topic == events.ORDER_REFUNDED:
                from melorin.modules.referral.service import on_order_refunded

                await on_order_refunded(session, uuid.UUID(str(p["order_id"])))
                await _webhook(session, "order.refunded", p, f"order.refunded:{p.get('order_id')}")
            elif e.topic == events.VPN_REVOKE:
                await revoke_account(session, uuid.UUID(str(p["vpn_account_id"])))
            elif e.topic == events.VPN_RENEWAL_ROLLBACK:
                await rollback_renewal(session, p)
            elif e.topic == events.NOTIFY:
                await _notify(session, p, p.get("kind", "general"), p.get("title", "Melorin"), p.get("body", ""))
                if p.get("store_id") and p.get("kind") in ("vpn_expired", "vpn_near_expiry"):
                    await _webhook(
                        session,
                        "vpn_account.expired" if p.get("kind") == "vpn_expired" else "vpn_account.near_expiry",
                        p,
                        f"{p.get('kind')}:{p.get('dedup_key') or p.get('user_id')}",
                    )
            elif e.topic == events.EVENT_CENTER:
                await _event_center(session, p)
            elif e.topic == events.TICKET_UPDATED:
                await _event_center(session, p)
            elif e.topic == events.PAYMENT_SUCCEEDED:
                await _webhook(session, "payment.succeeded", p, f"payment.succeeded:{p.get('payment_id')}")
            elif e.topic == events.PAYMENT_FAILED:
                await _webhook(session, "payment.failed", p, f"payment.failed:{p.get('payment_id')}")
            elif e.topic == events.WALLET_CHANGED:
                await _webhook(session, "wallet.changed", p, f"wallet.changed:{p.get('wallet_id')}:{p.get('amount')}:{p.get('balance')}")
            elif e.topic == events.RESELLER_DEBT:
                await _webhook(session, "reseller.debt", p, f"reseller.debt:{p.get('store_id')}:{p.get('state')}:{p.get('balance')}")
            e.status, e.processed_at, e.last_error = "processed", utcnow(), None
            await session.commit()
            inc("melorin_outbox_events_total", topic=e.topic, result="processed")
        except Exception as ex:
            log.exception("outbox failed %s", event_id)
            failed = await session.get(OutboxEvent, event_id, with_for_update=True)
            if failed is not None and failed.status == "processing":
                failed.status, failed.attempts, failed.last_error = "pending", failed.attempts + 1, str(ex)
                failed.available_at = utcnow() + dt.timedelta(seconds=min(1800, 2 ** min(failed.attempts, 8)))
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
    from melorin.modules.identity.models import Identity

    identity = await session.scalar(select(Identity).where(Identity.user_id == user_id, Identity.provider == "telegram"))
    if not identity:
        n.telegram_status = "skipped"
        return
    from melorin.modules.stores.models import Store

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
    # Implemented as an outbox consumer boundary; Telegram group/topic adapter plugs in here.
    log.info("event-center store=%s topic=%s text=%s", p.get("store_id"), p.get("topic"), p.get("text"))


async def revoke_account(session, account_id):
    a = await session.get(VpnAccount, account_id)
    if not a or not a.panel_id:
        return
    panel = await session.get(Panel, a.panel_id)
    await build_adapter(panel).revoke_account(a.username)
    a.status = "revoked"
    await session.commit()


async def rollback_renewal(session, payload):
    account = await session.get(VpnAccount, uuid.UUID(str(payload["vpn_account_id"])), with_for_update=True)
    if not account or not account.panel_id:
        return
    before = payload.get("before") or {}
    panel = await session.get(Panel, account.panel_id)
    pa = await build_adapter(panel).extend_account(
        account.username,
        expire_at=dt.datetime.fromisoformat(before["expires_at"]) if before.get("expires_at") else None,
        traffic_bytes=int(before.get("traffic_limit_bytes") or 0),
    )
    account.expires_at, account.traffic_limit_bytes = pa.expire_at, pa.traffic_limit_bytes
    await session.commit()


async def claim_webhook_batch(session, n=20):
    from melorin.modules.webhooks.models import WebhookDelivery

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
