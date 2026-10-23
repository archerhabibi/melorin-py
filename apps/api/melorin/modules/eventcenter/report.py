"""Nightly report of the Event Center (SRS §17): one summary of the last 24 hours per configured group.

The Admin's group gets the numbers of the whole platform, each reseller's group only the numbers of its own store.
``run`` is idempotent per Tehran calendar day and destination (dedup key = ``daily:<date>:<store|admin>``), so a restarted or
doubled cron never sends the same night twice.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from melorin.core.db import utcnow
from melorin.domain.order_state import OrderStatus, PaymentStatus
from melorin.kernel.models.notifications import TelegramEventDestination
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.referral import Commission, ReferralRelationship
from melorin.kernel.models.tickets import Ticket
from melorin.modules.eventcenter import service, topics

log = logging.getLogger("melorin.eventcenter")

_TEHRAN_FALLBACK = dt.timezone(dt.timedelta(hours=3, minutes=30))  # Iran has no daylight saving time any more


def _tehran() -> dt.tzinfo:
    try:
        return ZoneInfo("Asia/Tehran")
    except ZoneInfoNotFoundError:  # a slim container without tzdata
        return _TEHRAN_FALLBACK


def _money(rows: list[tuple[str, int]]) -> str:
    """``[(currency, total)]`` -> ``1,200,000 IRT`` (one part per currency, never mixed)."""
    parts = [f"{int(total or 0):,} {cur}" for cur, total in rows if total]
    return " + ".join(parts) if parts else "۰"


async def _by_currency(session, count_col, amount, currency_col, *where) -> tuple[int, list[tuple[str, int]]]:
    rows = (
        await session.execute(
            select(currency_col, func.count(count_col), func.coalesce(func.sum(amount), 0)).where(*where).group_by(currency_col)
        )
    ).all()
    return sum(int(r[1]) for r in rows), [(r[0], int(r[2])) for r in rows]


async def _count(session, col, *where) -> int:
    return int(await session.scalar(select(func.count(col)).where(*where)) or 0)


async def build(session, store_id: uuid.UUID | None, start: dt.datetime, end: dt.datetime, label: str) -> str:
    """The report text for one scope: a reseller store, or (``store_id`` None) the whole platform."""

    def scope(col):
        return [] if store_id is None else [col == store_id]

    sales_n, sales = await _by_currency(
        session,
        Order.id,
        Order.total,
        Order.currency,
        Order.status == OrderStatus.COMPLETED.value,
        Order.kind != "test",
        Order.completed_at >= start,
        Order.completed_at < end,
        *scope(Order.store_id),
    )
    tests_n = await _count(
        session, Order.id, Order.kind == "test", Order.completed_at >= start, Order.completed_at < end, *scope(Order.store_id)
    )
    paid_n, paid = await _by_currency(
        session,
        Payment.id,
        Payment.amount,
        Payment.currency,
        Payment.status == PaymentStatus.SUCCEEDED.value,
        Payment.updated_at >= start,
        Payment.updated_at < end,
        *scope(Payment.store_id),
    )
    failed_n = await _count(
        session,
        Payment.id,
        Payment.status == PaymentStatus.FAILED.value,
        Payment.updated_at >= start,
        Payment.updated_at < end,
        *scope(Payment.store_id),
    )
    tickets_n = await _count(session, Ticket.id, Ticket.created_at >= start, Ticket.created_at < end, *scope(Ticket.store_id))
    refs_n = await _count(
        session,
        ReferralRelationship.id,
        ReferralRelationship.created_at >= start,
        ReferralRelationship.created_at < end,
        *scope(ReferralRelationship.store_id),
    )
    comm_n, comm = await _by_currency(
        session,
        Commission.id,
        Commission.amount - Commission.offset_amount,
        Commission.currency,
        Commission.created_at >= start,
        Commission.created_at < end,
        *scope(Commission.store_id),
    )
    # What still waits for a person right now (not limited to the last 24 hours).
    receipts = await _count(session, Payment.id, Payment.status == PaymentStatus.AWAITING_REVIEW.value, *scope(Payment.store_id))
    open_tickets = await _count(session, Ticket.id, Ticket.status == "open", *scope(Ticket.store_id))
    review = await _count(session, Order.id, Order.needs_review.is_(True), *scope(Order.store_id))

    admin = store_id is None
    lines = [
        f"📊 گزارش شبانه — {label}",
        f"{'کل پلتفرم' if admin else 'فروشگاه شما'} · ۲۴ ساعت گذشته",
        "",
        f"🛒 فروش: {sales_n:,} سفارش — {_money(sales)}",
        f"💳 پرداخت موفق: {paid_n:,} — {_money(paid)}  |  ناموفق: {failed_n:,}",
        f"🧪 اکانت تست: {tests_n:,}",
        f"🎫 تیکت جدید: {tickets_n:,}",
    ]
    if admin:  # the referral program belongs to the Main Store only
        lines.append(f"🤝 معرف جدید: {refs_n:,}  |  کمیسیون: {comm_n:,} مورد — {_money(comm)}")
    lines += ["", f"⏳ در انتظار شما: رسید {receipts:,} · تیکت باز {open_tickets:,} · سفارش نیازمند بررسی {review:,}"]
    return "\n".join(lines)


async def run(session, *, now: dt.datetime | None = None) -> int:
    """Queue tonight's report for every enabled group. The caller commits.

    Returns how many groups the report was routed to. Running it again for the same Tehran day routes it again but adds no
    row (deduplicated per day and destination), so a doubled cron never sends the same night twice."""
    end = now or utcnow()
    start = end - dt.timedelta(hours=24)
    label = end.astimezone(_tehran()).date().isoformat()
    dests = (await session.scalars(select(TelegramEventDestination).where(TelegramEventDestination.is_enabled.is_(True)))).all()
    queued = 0
    for dest in dests:
        try:
            async with session.begin_nested():
                text = await build(session, dest.store_id, start, end, label)
                queued += await service.publish(
                    session,
                    store_id=dest.store_id,
                    topic=topics.DAILY,
                    text=text,
                    source_key=f"daily:{label}:{dest.store_id or 'admin'}",
                )
        except Exception:
            log.exception("event-center nightly report failed destination=%s", dest.id)
    return queued
