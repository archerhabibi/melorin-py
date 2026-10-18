"""Daily sales/orders time series for the Admin dashboard.

Currency-safe: amounts are never summed across currencies (one series per currency).
A sale is a *succeeded* payment, dated by its review time when it has one (manual
card approval) and by its creation time otherwise (gateway). Days default to UTC
and can be bucketed in any IANA time zone (``tz``); they are zero-filled so charts
get a continuous axis.

M6.9: the ``orders`` series counts *sold* orders (payment received and not unwound,
see ``SOLD_STATUSES``) so it describes the same population as the sales series;
``orders_all`` keeps the raw count of every order regardless of status.
"""

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.domain.order_state import OrderStatus
from melorin.modules.orders.models import Order
from melorin.modules.payments.models import Payment

MIN_DAYS, MAX_DAYS = 7, 90

# Orders whose payment was received and not (being) unwound: the population behind "sales".
SOLD_STATUSES = (
    OrderStatus.PAID,
    OrderStatus.PROCESSING,
    OrderStatus.PROVISIONING,
    OrderStatus.COMPLETED,
    OrderStatus.PROVISIONING_FAILED,
    OrderStatus.MANUAL_REVIEW,
)


def resolve_zone(tz: str | None) -> ZoneInfo:
    """IANA zone for ``tz`` (default UTC). Raises ``ValueError`` for unknown names."""
    name = (tz or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:  # ValueError: malformed key
        raise ValueError(f"unknown time zone: {name!r}") from exc


def day_axis(days: int, now: dt.datetime | None = None, zone: dt.tzinfo = dt.UTC) -> list[str]:
    today = (now or utcnow()).astimezone(zone).date()
    return [(today - dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def local_day(column, dialect_name: str, tz: str = "UTC"):
    """Calendar day of ``column`` in zone ``tz`` (SQL side; PostgreSQL, or UTC on SQLite)."""
    if dialect_name == "postgresql":
        return func.date(func.timezone(tz, column))
    return func.date(column)


def utc_day(column, dialect_name: str):
    """Calendar day of ``column`` in UTC.

    ``date(timestamptz)`` uses the *database session* time zone on PostgreSQL, so on a server that is not
    set to UTC a sale made late in the UTC day lands on the next day, outside the UTC axis, and is silently
    dropped from the chart (M-bug). Convert to UTC explicitly. SQLite stores naive UTC, so plain ``date`` is exact.
    """
    return local_day(column, dialect_name, "UTC")


def fill(axis: list[str], rows: list[tuple]) -> list[int]:
    """rows: (day, value) pairs; days outside the axis are ignored, gaps become 0."""
    by_day = {str(d)[:10]: int(v or 0) for d, v in rows}
    return [by_day.get(d, 0) for d in axis]


def _local_date(value: dt.datetime, zone: dt.tzinfo) -> str:
    if value.tzinfo is None:  # SQLite returns naive UTC
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(zone).date().isoformat()


async def build_timeseries(session: AsyncSession, days: int = 30, now: dt.datetime | None = None, tz: str = "UTC") -> dict:
    days = max(MIN_DAYS, min(MAX_DAYS, days))
    zone = resolve_zone(tz)
    tz_name = zone.key if isinstance(zone, ZoneInfo) else "UTC"
    axis = day_axis(days, now, zone)
    since = dt.datetime.fromisoformat(axis[0]).replace(tzinfo=zone).astimezone(dt.UTC)
    sale_at = func.coalesce(Payment.reviewed_at, Payment.created_at)
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
    sold = [s.value for s in SOLD_STATUSES]
    sql_side = dialect == "postgresql" or tz_name == "UTC"

    if sql_side:
        sale_day = local_day(sale_at, dialect, tz_name)
        pay_rows = (
            await session.execute(
                select(Payment.currency, sale_day, func.count(Payment.id), func.sum(Payment.amount))
                .where(Payment.status == "succeeded", sale_at >= since)
                .group_by(Payment.currency, sale_day)
            )
        ).all()
        order_day = local_day(Order.created_at, dialect, tz_name)
        order_all_rows = (
            await session.execute(select(order_day, func.count(Order.id)).where(Order.created_at >= since).group_by(order_day))
        ).all()
        order_rows = (
            await session.execute(
                select(order_day, func.count(Order.id)).where(Order.created_at >= since, Order.status.in_(sold)).group_by(order_day)
            )
        ).all()
    else:
        # SQLite (dev/tests) has no zone database in SQL: bucket in Python, DST-correct.
        buckets: dict[tuple[str, str], list[int]] = {}
        for currency, at, amount in (
            await session.execute(select(Payment.currency, sale_at, Payment.amount).where(Payment.status == "succeeded", sale_at >= since))
        ).all():
            cell = buckets.setdefault((currency, _local_date(at, zone)), [0, 0])
            cell[0] += 1
            cell[1] += int(amount or 0)
        pay_rows = [(cur, day, n, total) for (cur, day), (n, total) in buckets.items()]
        all_counts: dict[str, int] = {}
        sold_counts: dict[str, int] = {}
        for at, status in (await session.execute(select(Order.created_at, Order.status).where(Order.created_at >= since))).all():
            day = _local_date(at, zone)
            all_counts[day] = all_counts.get(day, 0) + 1
            if status in sold:
                sold_counts[day] = sold_counts.get(day, 0) + 1
        order_all_rows, order_rows = list(all_counts.items()), list(sold_counts.items())

    currencies = sorted({r[0] for r in pay_rows})
    return {
        "days": axis,
        "timezone": tz_name,
        "orders": fill(axis, [(d, n) for d, n in order_rows]),
        "orders_all": fill(axis, [(d, n) for d, n in order_all_rows]),
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
