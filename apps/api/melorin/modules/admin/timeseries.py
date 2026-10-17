"""Daily sales/orders time series for the Admin dashboard.

Currency-safe: amounts are never summed across currencies (one series per currency).
A sale is a *succeeded* payment, dated by its review time when it has one (manual
card approval) and by its creation time otherwise (gateway). Days are UTC and
zero-filled so charts get a continuous axis.
"""

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.modules.orders.models import Order
from melorin.modules.payments.models import Payment

MIN_DAYS, MAX_DAYS = 7, 90


def day_axis(days: int, now: dt.datetime | None = None) -> list[str]:
    today = (now or utcnow()).astimezone(dt.UTC).date()
    return [(today - dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def utc_day(column, dialect_name: str):
    """Calendar day of ``column`` in UTC.

    ``date(timestamptz)`` uses the *database session* time zone on PostgreSQL, so on a server that is not
    set to UTC a sale made late in the UTC day lands on the next day, outside the UTC axis, and is silently
    dropped from the chart (M-bug). Convert to UTC explicitly. SQLite stores naive UTC, so plain ``date`` is exact.
    """
    if dialect_name == "postgresql":
        return func.date(func.timezone("UTC", column))
    return func.date(column)


def fill(axis: list[str], rows: list[tuple]) -> list[int]:
    """rows: (day, value) pairs; days outside the axis are ignored, gaps become 0."""
    by_day = {str(d)[:10]: int(v or 0) for d, v in rows}
    return [by_day.get(d, 0) for d in axis]


async def build_timeseries(session: AsyncSession, days: int = 30, now: dt.datetime | None = None) -> dict:
    days = max(MIN_DAYS, min(MAX_DAYS, days))
    axis = day_axis(days, now)
    since = dt.datetime.fromisoformat(axis[0]).replace(tzinfo=dt.UTC)
    sale_at = func.coalesce(Payment.reviewed_at, Payment.created_at)
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
    sale_day = utc_day(sale_at, dialect)
    pay_rows = (
        await session.execute(
            select(Payment.currency, sale_day, func.count(Payment.id), func.sum(Payment.amount))
            .where(Payment.status == "succeeded", sale_at >= since)
            .group_by(Payment.currency, sale_day)
        )
    ).all()
    order_day = utc_day(Order.created_at, dialect)
    order_rows = (await session.execute(select(order_day, func.count(Order.id)).where(Order.created_at >= since).group_by(order_day))).all()
    currencies = sorted({r[0] for r in pay_rows})
    return {
        "days": axis,
        "orders": fill(axis, [(d, n) for d, n in order_rows]),
        "payments": [
            {
                "currency": c,
                "amounts": fill(axis, [(d, total) for cur, d, _n, total in pay_rows if cur == c]),
                "counts": fill(axis, [(d, n) for cur, d, n, _t in pay_rows if cur == c]),
            }
            for c in currencies
        ],
        "currency_safe": True,
    }
