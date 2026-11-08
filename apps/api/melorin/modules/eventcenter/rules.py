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


async def _order_rule(session, label: str, p: dict, *, test_text: str | None = None) -> tuple[uuid.UUID | None, str, str] | None:
    """A test order is free and has no sale to report: it is announced only when it completes, in the test-accounts topic
    (``test_text``); every other test-order event stays silent. Real orders go to the orders topic."""
    order = await _order(session, p)
    if order is None:
        return None
    if order.kind == "test":
        return (order.store_id, topics.TESTS, f"{test_text}\nسفارش: {order.number}") if test_text else None
    return order.store_id, topics.ORDERS, f"{label}\nسفارش: {order.number}\nمبلغ: {_money(order.total, order.currency)}"


async def _paid(session, e, p):
    return await _order_rule(session, "🛒 سفارش پرداخت شد", p)


async def _completed(session, e, p):
    return await _order_rule(session, "✅ سفارش تکمیل شد", p, test_text="🧪 اکانت تست ساخته شد")


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


async def notify_panel_health(session, panel, previous: str | None) -> None:
    """Tell the admin's errors topic when a panel turns unhealthy (and when it recovers).

    Called by the health job and the manual health check with the status the panel had *before* this check, so a panel
    that stays unhealthy does not repeat the message every 5 minutes. ``degraded`` (some node failing, panel still serving) is
    announced by :func:`notify_panel_nodes`, which names the nodes and the fix. Best-effort: it can never fail the health check.
    """
    now = panel.health_status
    if now == previous:
        return
    if now == "unhealthy":
        error = str(panel.last_health_error or "نامشخص")[:250]
        text = f"🔴 پنل «{panel.name}» ناسالم شد\nخطا: {error}"
    elif now == "healthy" and previous == "unhealthy":
        text = f"🟢 پنل «{panel.name}» دوباره سالم شد"
    elif now == "degraded" and previous == "unhealthy":
        text = f"🟠 پنل «{panel.name}» پاسخ می‌دهد ولی بعضی نودها خطا دارند"
    else:
        return
    try:
        async with session.begin_nested():
            await events.emit(session, events.EVENT_CENTER, {"store_id": None, "topic": topics.ERRORS, "text": text})
    except Exception:
        log.exception("event-center panel health notice failed panel=%s", panel.id)


async def notify_settings_drift(session, panel, before: int, after: int) -> None:
    """Announce (once) that a panel's settings started to differ from what Melorin needs, and when that is fixed (PG-15).

    Only the change 0 -> N and N -> 0 is announced, so an unfixed drift does not repeat every hour. Findings are named by key; no value
    read from the panel's settings is ever put in the message. Best-effort: it can never fail the drift check."""
    if (before > 0) == (after > 0):
        return
    keys = ", ".join(f["key"] for f in (panel.settings_drift or {}).get("findings", []) if f.get("state") == "drift")
    text = (
        f"🟠 تنظیمات پنل «{panel.name}» با نیاز ملورین هم‌خوان نیست ({keys})؛ بخش «رانش تنظیمات» پنل را ببینید."
        if after > 0
        else f"🟢 تنظیمات پنل «{panel.name}» دوباره با ملورین هم‌خوان شد"
    )
    try:
        async with session.begin_nested():
            await events.emit(session, events.EVENT_CENTER, {"store_id": None, "topic": topics.ERRORS, "text": text})
    except Exception:
        log.exception("event-center settings drift notice failed panel=%s", panel.id)


def panel_nodes_text(panel_name: str, changes: list[dict]) -> str | None:
    """One message per panel and check for every node that started or stopped failing (a 4-node outage is ONE notice)."""
    failed = [c for c in changes if c["to"] in ("error", "limited", "unknown")]
    recovered = [c for c in changes if c["from"] in ("error", "limited", "unknown") and c["to"] not in ("error", "limited", "unknown")]
    lines: list[str] = []
    if failed:
        lines.append(f"🟠 نود(های) پنل «{panel_name}» خطا دارند:")
        for c in failed[:8]:
            msg = str(c.get("message") or "").strip()[:120]
            lines.append(f"• {c['name']}" + (f" — {msg}" if msg else ""))
        if len(failed) > 8:
            lines.append(f"… و {len(failed) - 8} نود دیگر")
    if recovered:
        lines.append(f"🟢 نود(های) پنل «{panel_name}» دوباره سالم شدند: " + "، ".join(c["name"] for c in recovered[:8]))
    return "\n".join(lines) or None


async def notify_panel_nodes(session, panel, changes: list[dict]) -> None:
    """Event Center notice for node status transitions found by the health job (PG-01). Best-effort."""
    text = panel_nodes_text(panel.name, changes)
    if not text:
        return
    try:
        async with session.begin_nested():
            await events.emit(session, events.EVENT_CENTER, {"store_id": None, "topic": topics.ERRORS, "text": text})
    except Exception:
        log.exception("event-center panel node notice failed panel=%s", panel.id)


def server_capacity_text(panel_name: str, changes: list) -> str | None:
    """One message per panel and check: destinations that stopped/started being sellable and capacity thresholds crossed (PG-08)."""
    lines: list[str] = []
    blocked = [c for c in changes if c.kind == "sellable" and c.new == "blocked"]
    back = [c for c in changes if c.kind == "sellable" and c.new == "sellable"]
    if blocked:
        lines.append(f"🔴 مقصدهای پنل «{panel_name}» از فروش خارج شدند (اکانت‌های موجود تغییری نمی‌کنند):")
        for c in blocked[:8]:
            lines.append(f"• {c.server}" + (f" — {str(c.detail)[:140]}" if c.detail else ""))
    if back:
        lines.append(f"🟢 مقصدهای پنل «{panel_name}» دوباره قابل فروش شدند: " + "، ".join(c.server for c in back[:8]))
    labels = {"80": "🟡 بیش از ۸۰٪ پر شد", "95": "🟠 بیش از ۹۵٪ پر شد", "100": "🔴 ظرفیت پر شد"}
    for c in changes:
        if c.kind == "capacity" and c.new in labels:
            lines.append(f"{labels[c.new]}: {c.server} (پنل «{panel_name}»)")
    return "\n".join(lines) or None


async def notify_server_capacity(session, panel, changes: list) -> None:
    """Event Center notice for sell-guard flips and capacity thresholds (PG-08). Best-effort."""
    text = server_capacity_text(panel.name, changes)
    if not text:
        return
    try:
        async with session.begin_nested():
            await events.emit(session, events.EVENT_CENTER, {"store_id": None, "topic": topics.ERRORS, "text": text})
    except Exception:
        log.exception("event-center server capacity notice failed panel=%s", panel.id)


def _size(n: int | None) -> str:
    if not n:
        return "نامشخص"
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)} KB"


def backup_text(status: str, size: int | None, details: str | None, target: str = "melorin") -> str:
    """The admin-facing text of one backup run. The server path is never included; error detail is clipped."""
    label = "پشتیبان‌گیری از پنل پاسارگارد" if target == "panel" else "پشتیبان‌گیری"
    if status == "succeeded":
        where = "کپی روی S3 هم انجام شد" if "copied to S3" in (details or "") else "فقط روی سرور (ارسال به S3 غیرفعال است)"
        return f"💾 {label} موفق بود\nحجم: {_size(size)}\n{where}"
    if status == "partial":
        head = "🟠 پشتیبان محلی پنل پاسارگارد ساخته شد ولی ارسال به S3 ناموفق بود" if target == "panel" else "🟠 پشتیبان محلی ساخته شد ولی ارسال به S3 ناموفق بود"
        return f"{head}\nحجم: {_size(size)}\nخطا: {str(details or '')[-250:]}"
    return f"🔴 {label} ناموفق بود\nخطا: {str(details or 'نامشخص')[:250]}"


async def notify_backup(session, run) -> None:
    """Tell the admin's backup topic how a backup run ended (once per run). Best-effort: a failed notice never fails the backup."""
    try:
        async with session.begin_nested():
            await events.emit(
                session,
                events.EVENT_CENTER,
                {"store_id": None, "topic": topics.BACKUP, "text": backup_text(run.status, run.size, run.details, getattr(run, "target", "melorin"))},
                dedup_key=f"ec:backup:{run.id}",
            )
    except Exception:
        log.exception("event-center backup notice failed run=%s", getattr(run, "id", None))
