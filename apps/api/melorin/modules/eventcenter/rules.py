"""Event Center rules: which outbox events become which Telegram message in which topic (SRS §17).

``tap`` is called by the worker after the normal handler of an outbox event succeeded. It is best-effort and runs inside a
SAVEPOINT, so a bug here can never undo or repeat the money/order work the event stands for.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select

from melorin.core import events
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.tickets import Ticket, TicketMessage
from melorin.modules.eventcenter import service, topics

log = logging.getLogger("melorin.eventcenter")

OUTBOX_FAILURE_THRESHOLD = 5  # an outbox event that failed this many times is reported once to the errors topic

Rule = Callable[[object, OutboxEvent, dict], Awaitable[tuple[uuid.UUID | None, str, str] | None]]
# A rule returns (store_id, topic, text) or None when the event is not worth a message.


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _money(amount: int | None, currency: str | None = None) -> str:
    return f"{int(amount or 0):,}" + (f" {currency}" if currency else "")


async def _order(session, p: dict) -> Order | None:
    oid = _uuid(p.get("order_id"))
    return await session.get(Order, oid) if oid else None


async def _order_rule(session, label: str, p: dict) -> tuple[uuid.UUID | None, str, str] | None:
    order = await _order(session, p)
    if order is None:
        return None
    return order.store_id, topics.ORDERS, f"{label}\nسفارش: {order.number}\nمبلغ: {_money(order.total, order.currency)}"


async def _paid(session, e, p):
    return await _order_rule(session, "🛒 سفارش پرداخت شد", p)


async def _completed(session, e, p):
    return await _order_rule(session, "✅ سفارش تکمیل شد", p)


async def _refunded(session, e, p):
    return await _order_rule(session, "↩️ سفارش بازگشت وجه شد", p)


async def _payment(session, label: str, p: dict) -> tuple[uuid.UUID | None, str, str] | None:
    pid = _uuid(p.get("payment_id"))
    pay = await session.get(Payment, pid) if pid else None
    if pay is None:
        return None
    return pay.store_id, topics.PAYMENTS, f"{label}\nمبلغ: {_money(pay.amount, pay.currency)}\nروش: {pay.provider}\nشناسه: {pay.id}"


async def _pay_ok(session, e, p):
    return await _payment(session, "💳 پرداخت موفق", p)


async def _pay_failed(session, e, p):
    return await _payment(session, "⚠️ پرداخت ناموفق", p)


async def _debt(session, e, p):
    store_id, state = _uuid(p.get("store_id")), str(p.get("state") or "")
    if store_id is None:
        return None
    if state == "reached":
        return store_id, topics.DEBT, "⛔ سقف بدهی نماینده پر شد؛ فروش این فروشگاه متوقف است."
    if state == "near":
        line = f"\nتراز: {_money(p.get('balance'))}  سقف: {_money(p.get('limit'))}" if p.get("limit") is not None else ""
        return store_id, topics.DEBT, f"🟠 بدهی نماینده نزدیک سقف است.{line}"
    return None


async def _provisioning_failed(session, e, p):
    order = await _order(session, p)
    if order is None:
        return None
    error = str(p.get("error") or "نامشخص")[:300]
    return order.store_id, topics.ERRORS, f"❗ ساخت اکانت ناموفق بود\nسفارش: {order.number}\nخطا: {error}"


async def _ticket(session, e, p):
    """Announce only a customer's own message (new ticket / new reply).

    The event names the message (``message_id``). Status or priority changes, staff replies and internal notes carry no
    customer message, so they stay silent - otherwise every status change would repeat the last customer reply.
    """
    mid = _uuid(p.get("message_id"))
    message = await session.get(TicketMessage, mid) if mid else None
    if message is None or message.is_staff or message.is_internal:
        return None
    ticket = await session.get(Ticket, message.ticket_id)
    if ticket is None:
        return None
    count = await session.scalar(select(func.count()).select_from(TicketMessage).where(TicketMessage.ticket_id == ticket.id)) or 0
    head = "🎫 تیکت جدید" if count <= 1 else "💬 پاسخ جدید مشتری در تیکت"
    return ticket.store_id, topics.TICKETS, f"{head}\nتیکت: {ticket.number}\nموضوع: {ticket.subject[:120]}"


async def _manual(session, e, p):
    """Events written straight for the Event Center (``eventcenter.send``): payload carries store_id / topic / text."""
    topic, text = str(p.get("topic") or ""), str(p.get("text") or "")
    if topic not in topics.TOPICS or not text:
        return None
    return _uuid(p.get("store_id")), topic, text


RULES: dict[str, Rule] = {
    events.ORDER_PAID: _paid,
    events.ORDER_COMPLETED: _completed,
    events.ORDER_REFUNDED: _refunded,
    events.PAYMENT_SUCCEEDED: _pay_ok,
    events.PAYMENT_FAILED: _pay_failed,
    events.RESELLER_DEBT: _debt,
    events.PROVISIONING_FAILED: _provisioning_failed,
    events.TICKET_UPDATED: _ticket,
    events.EVENT_CENTER: _manual,
}


async def tap(session, e: OutboxEvent) -> int:
    """Queue the Telegram deliveries for one processed outbox event. Never raises; returns how many were queued."""
    rule = RULES.get(e.topic)
    if rule is None:
        return 0
    try:
        async with session.begin_nested():
            hit = await rule(session, e, e.payload or {})
            if hit is None:
                return 0
            store_id, topic, text = hit
            return await service.publish(session, store_id=store_id, topic=topic, text=text, source_key=str(e.id))
    except Exception:
        log.exception("event-center rule failed topic=%s event=%s", e.topic, e.id)
        return 0


async def report_outbox_failure(session, e: OutboxEvent) -> None:
    """An outbox event that keeps failing is reported once (dedup by event id) to the admin's errors topic."""
    if e.attempts != OUTBOX_FAILURE_THRESHOLD or e.topic in (events.EVENT_CENTER_DELIVER,):
        return
    try:
        async with session.begin_nested():
            text = f"🛑 رویداد {e.topic} بارها ناموفق بود ({e.attempts} بار)\nخطا: {str(e.last_error or '')[:250]}"
            await service.publish(session, store_id=None, topic=topics.ERRORS, text=text, source_key=f"fail:{e.id}")
    except Exception:
        log.exception("event-center failure report failed event=%s", e.id)
