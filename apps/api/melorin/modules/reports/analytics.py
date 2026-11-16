"""Admin analytics: one currency-safe payload that powers the "Reports & charts" screen.

Design rules (same family as ``timeseries.py``):

* **Currency-safe.** Money is never summed across currencies. The report is scoped to ONE currency (``currency`` query,
  default: the currency with the most sales in the period); the list of currencies seen is returned so the UI can switch.
* **Revenue** = orders that were *sold* (payment received and not unwound, see ``SOLD_STATUSES``), dated by ``paid_at``
  (``created_at`` when absent). **Cash-in** = succeeded payments (card top-ups, gateway), dated like the dashboard chart
  (review time, else creation time). They are different populations on purpose: a wallet-paid order is revenue but not cash-in.
* **Time zone aware.** Days are bucketed in an IANA zone (``tz``) in Python, so it is DST-correct on SQLite *and* PostgreSQL.
* **Period comparison.** Every KPI carries the previous period of the same length (``days``) for a delta.
* **Pure core.** ``compute_analytics`` takes plain rows and returns the payload, so it is unit-tested without a database.
  ``build_analytics`` only loads the (bounded) rows and attaches product / store names.

The implementation lives in ``analytics_compute``, ``analytics_queries``; this module stays the stable import surface.
"""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.modules.reports.analytics_compute import (  # noqa: F401
    ATTENTION,
    PAID_EVER,
    PROVISION_BAD,
    SOLD,
    TOP_N,
    OrderRow,
    PayRow,
    _day,
    _kpi,
    _peak,
    _ratio,
    compute_analytics,
    pct_change,
)
from melorin.modules.reports.analytics_queries import MAX_ROWS, _load, _names, _panel_aggregates, _snapshot  # noqa: F401
from melorin.modules.reports.timeseries import MAX_DAYS, MIN_DAYS, day_axis, resolve_zone


async def build_analytics(
    session: AsyncSession,
    days: int = 30,
    *,
    tz: str = "UTC",
    currency: str | None = None,
    store_id: uuid.UUID | None = None,
    now: dt.datetime | None = None,
) -> dict:
    days = max(MIN_DAYS, min(MAX_DAYS, days))
    zone = resolve_zone(tz)  # ValueError for an unknown zone: the router maps it to 422
    tz_name = zone.key if isinstance(zone, ZoneInfo) else "UTC"
    now = now or utcnow()
    axis = day_axis(days, now, zone)
    prev_axis = day_axis(days, now - dt.timedelta(days=days), zone)
    since = dt.datetime.fromisoformat(prev_axis[0]).replace(tzinfo=zone).astimezone(dt.UTC)
    orders, pays, users, truncated = await _load(session, since, store_id)
    payload = compute_analytics(orders, pays, users, axis=axis, prev_axis=prev_axis, zone=zone, currency=currency)
    await _names(session, payload)
    payload.update(await _snapshot(session, now))
    payload["period"] = {
        "days": days,
        "from": axis[0],
        "to": axis[-1],
        "previous_from": prev_axis[0],
        "previous_to": prev_axis[-1],
        "timezone": tz_name,
    }
    payload["scope"] = {"store_id": str(store_id) if store_id else None, "users_scoped": False}
    payload["truncated"] = truncated
    payload["generated_at"] = now.isoformat()
    payload["currency_safe"] = True
    return payload


CSV_SECTIONS = ("daily", "products", "stores", "methods")


def to_csv_rows(payload: dict, section: str) -> tuple[list[str], list[list]]:
    """Header + rows for one CSV section (``daily`` | ``products`` | ``stores`` | ``methods``)."""
    if section == "daily":
        s = payload["series"]
        head = ["day", "revenue", "orders_sold", "orders_created", "cash_in", "cash_in_count", "new_users", "currency"]
        rows = [
            [d, s["revenue"][i], s["orders"][i], s["orders_created"][i], s["cash_in"][i], s["cash_in_count"][i], s["new_users"][i], payload["currency"]]
            for i, d in enumerate(payload["days"])
        ]  # fmt: skip
        return head, rows
    if section == "products":
        return ["product_id", "name", "orders_sold", "revenue", "currency"], [
            [r["product_id"], r["name"], r["count"], r["revenue"], payload["currency"]] for r in payload["top_products"]
        ]
    if section == "stores":
        return ["store_id", "name", "kind", "orders_sold", "revenue", "wholesale_cost", "currency"], [
            [r["store_id"], r["name"], r["kind"], r["count"], r["revenue"], r["wholesale"], payload["currency"]]
            for r in payload["top_stores"]
        ]
    if section == "methods":
        return ["payment_method", "orders_sold", "revenue", "currency"], [
            [r["key"], r["count"], r["revenue"], payload["currency"]] for r in payload["by_method"]
        ]
    raise ValueError(f"unknown section: {section!r}")


__all__ = [
    "TOP_N",
    "SOLD",
    "PAID_EVER",
    "PROVISION_BAD",
    "ATTENTION",
    "OrderRow",
    "PayRow",
    "_day",
    "pct_change",
    "_kpi",
    "_ratio",
    "compute_analytics",
    "_peak",
    "MAX_ROWS",
    "_load",
    "_panel_aggregates",
    "_snapshot",
    "_names",
    "build_analytics",
    "CSV_SECTIONS",
    "to_csv_rows",
]
