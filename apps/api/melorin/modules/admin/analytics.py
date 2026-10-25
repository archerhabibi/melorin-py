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
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter, defaultdict
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.domain.order_state import OrderStatus
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import Store
from melorin.kernel.models.tickets import Ticket
from melorin.kernel.models.vpn import VpnAccount
from melorin.modules.admin.timeseries import MAX_DAYS, MIN_DAYS, SOLD_STATUSES, day_axis, resolve_zone

MAX_ROWS = 200_000  # per table and per request; ``truncated`` tells the UI when a window was cut
TOP_N = 8
SOLD = {s.value for s in SOLD_STATUSES}
PAID_EVER = SOLD | {OrderStatus.REFUND_PENDING.value, OrderStatus.REFUNDED.value}
PROVISION_BAD = {OrderStatus.PROVISIONING_FAILED.value, OrderStatus.MANUAL_REVIEW.value}
ATTENTION = PROVISION_BAD | {OrderStatus.PAYMENT_FAILED.value, OrderStatus.REFUND_PENDING.value}


class OrderRow(NamedTuple):
    created_at: dt.datetime
    paid_at: dt.datetime | None
    status: str
    total: int
    currency: str
    store_id: str
    product_id: str
    method: str
    channel: str
    kind: str
    reseller_cost: int | None


class PayRow(NamedTuple):
    created_at: dt.datetime
    reviewed_at: dt.datetime | None
    status: str
    amount: int
    currency: str
    provider: str
    purpose: str
    store_id: str


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value  # SQLite hands back naive UTC


def _day(value: dt.datetime, zone: dt.tzinfo) -> str:
    return _aware(value).astimezone(zone).date().isoformat()


def pct_change(cur: float, prev: float) -> float | None:
    """Relative change in percent; ``None`` when there is no previous value to compare with."""
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _kpi(cur: float, prev: float, spark: list[float] | None = None) -> dict:
    out = {"value": cur, "previous": prev, "delta_pct": pct_change(cur, prev)}
    if spark is not None:
        out["spark"] = spark
    return out


def _ratio(num: int, den: int) -> float:
    return round(num / den * 100, 1) if den else 0.0


def compute_analytics(
    orders: list[OrderRow],
    payments: list[PayRow],
    user_times: list[dt.datetime],
    *,
    axis: list[str],
    prev_axis: list[str],
    zone: dt.tzinfo,
    currency: str | None = None,
) -> dict:
    """Aggregate plain rows into the analytics payload. ``orders``/``payments`` may contain any currency and any date."""
    n = len(axis)
    cur_i = {d: i for i, d in enumerate(axis)}
    prev_i = {d: i for i, d in enumerate(prev_axis)}

    # --- which currency? (rank by sold revenue in the current period, then by order count) --------------------------
    revenue_by_cur: Counter[str] = Counter()
    seen: set[str] = set()
    for o in orders:
        seen.add(o.currency)
        if o.status in SOLD and _day(o.paid_at or o.created_at, zone) in cur_i:
            revenue_by_cur[o.currency] += int(o.total or 0)
    for p in payments:
        seen.add(p.currency)
    currencies = sorted(seen, key=lambda c: (-revenue_by_cur.get(c, 0), c))
    if currency not in seen:
        currency = currencies[0] if currencies else (currency or "IRT")

    def zeros() -> list[int]:
        return [0] * n

    def zeros_prev() -> list[int]:
        return [0] * len(prev_axis)

    rev, sold, rev_p, sold_p = zeros(), zeros(), zeros_prev(), zeros_prev()
    created, created_p = zeros(), zeros_prev()
    cash, cash_n, cash_p = zeros(), zeros(), zeros_prev()
    new_users, new_users_p = zeros(), zeros_prev()

    status_cnt: Counter[str] = Counter()
    status_cnt_p: Counter[str] = Counter()
    by_method: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_channel: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_kind: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_product: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_store: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # count, revenue, wholesale
    heat = [[0] * 24 for _ in range(7)]  # Monday=0 .. Sunday=6, local hour
    refunded, refunded_p = [0, 0], [0, 0]
    wholesale = 0
    paid_ever, paid_ever_p = 0, 0
    completed, completed_p = 0, 0
    prov_ok, prov_bad = 0, 0
    sold_prev_total = 0

    for o in orders:
        if o.currency != currency:
            continue
        c_day = _day(o.created_at, zone)
        in_cur_created, in_prev_created = c_day in cur_i, c_day in prev_i
        if in_cur_created:
            created[cur_i[c_day]] += 1
            status_cnt[o.status] += 1
            paid_ever += o.status in PAID_EVER
            completed += o.status == OrderStatus.COMPLETED.value
            prov_ok += o.status == OrderStatus.COMPLETED.value
            prov_bad += o.status in PROVISION_BAD
            if o.status == OrderStatus.REFUNDED.value:
                refunded[0] += 1
                refunded[1] += int(o.total or 0)
        elif in_prev_created:
            created_p[prev_i[c_day]] += 1
            status_cnt_p[o.status] += 1
            paid_ever_p += o.status in PAID_EVER
            completed_p += o.status == OrderStatus.COMPLETED.value
            if o.status == OrderStatus.REFUNDED.value:
                refunded_p[0] += 1
                refunded_p[1] += int(o.total or 0)
        if o.status not in SOLD:
            continue
        paid = _aware(o.paid_at or o.created_at)
        s_day = _day(paid, zone)
        total = int(o.total or 0)
        if s_day in cur_i:
            i = cur_i[s_day]
            rev[i] += total
            sold[i] += 1
            for bucket, key in ((by_method, o.method), (by_channel, o.channel), (by_kind, o.kind), (by_product, o.product_id)):
                bucket[key][0] += 1
                bucket[key][1] += total
            st = by_store[o.store_id]
            st[0] += 1
            st[1] += total
            if o.reseller_cost is not None:
                st[2] += int(o.reseller_cost)
                wholesale += int(o.reseller_cost)
            local = paid.astimezone(zone)
            heat[local.weekday()][local.hour] += 1
        elif s_day in prev_i:
            rev_p[prev_i[s_day]] += total
            sold_p[prev_i[s_day]] += 1
            sold_prev_total += total

    # --- payments (cash-in + provider health) -------------------------------------------------------------------
    providers: dict[str, Counter[str]] = defaultdict(Counter)
    for p in payments:
        if p.currency != currency:
            continue
        if p.status == "succeeded":
            s_day = _day(p.reviewed_at or p.created_at, zone)
            if s_day in cur_i:
                i = cur_i[s_day]
                cash[i] += int(p.amount or 0)
                cash_n[i] += 1
                providers[p.provider]["succeeded"] += 1
                providers[p.provider]["amount"] += int(p.amount or 0)
            elif s_day in prev_i:
                cash_p[prev_i[s_day]] += int(p.amount or 0)
        else:
            if _day(p.created_at, zone) in cur_i:
                providers[p.provider][p.status] += 1

    for t in user_times:
        d = _day(t, zone)
        if d in cur_i:
            new_users[cur_i[d]] += 1
        elif d in prev_i:
            new_users_p[prev_i[d]] += 1

    # --- headline numbers -------------------------------------------------------------------------------------
    rev_total, rev_prev_total = sum(rev), sum(rev_p)
    sold_total, sold_prev_n = sum(sold), sum(sold_p)
    created_total, created_prev_total = sum(created), sum(created_p)
    aov = round(rev_total / sold_total) if sold_total else 0
    aov_p = round(rev_prev_total / sold_prev_n) if sold_prev_n else 0
    conv, conv_p = _ratio(paid_ever, created_total), _ratio(paid_ever_p, created_prev_total)
    daily_aov = [round(r / s) if s else 0 for r, s in zip(rev, sold, strict=True)]

    cumulative, running = [], 0
    for v in rev:
        running += v
        cumulative.append(running)

    best_i = max(range(n), key=lambda i: rev[i]) if n and any(rev) else None

    def _top(bucket: dict[str, list[int]], key: str, with_wholesale: bool = False) -> list[dict]:
        rows = sorted(bucket.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))[:TOP_N]
        return [{key: k, "count": v[0], "revenue": v[1], **({"wholesale": v[2]} if with_wholesale else {})} for k, v in rows]

    def _split(bucket: dict[str, list[int]]) -> list[dict]:
        return [{"key": k, "count": v[0], "revenue": v[1]} for k, v in sorted(bucket.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))]

    provider_rows = []
    for name, c in providers.items():
        ok, bad = c.get("succeeded", 0), c.get("failed", 0) + c.get("cancelled", 0)
        provider_rows.append(
            {
                "provider": name,
                "succeeded": ok,
                "failed": bad,
                "awaiting_review": c.get("awaiting_review", 0),
                "amount": c.get("amount", 0),
                "success_rate": _ratio(ok, ok + bad),
            }
        )
    provider_rows.sort(key=lambda r: (-r["amount"], r["provider"]))

    return {
        "currency": currency,
        "currencies": currencies or [currency],
        "days": axis,
        "kpis": {
            "revenue": _kpi(rev_total, rev_prev_total, rev),
            "orders_sold": _kpi(sold_total, sold_prev_n, sold),
            "avg_order_value": _kpi(aov, aov_p, daily_aov),
            "cash_in": _kpi(sum(cash), sum(cash_p), cash),
            "new_users": _kpi(sum(new_users), sum(new_users_p), new_users),
            "conversion_pct": _kpi(conv, conv_p),
            "orders_created": _kpi(created_total, created_prev_total, created),
            "refunds": {
                "count": refunded[0],
                "amount": refunded[1],
                "previous_count": refunded_p[0],
                "previous_amount": refunded_p[1],
                "rate_pct": _ratio(refunded[0], paid_ever),
            },
        },
        "series": {
            "revenue": rev,
            "revenue_prev": rev_p,
            "orders": sold,
            "orders_prev": sold_p,
            "orders_created": created,
            "cash_in": cash,
            "cash_in_count": cash_n,
            "new_users": new_users,
            "cumulative_revenue": cumulative,
            "avg_order_value": daily_aov,
        },
        "highlights": {
            "best_day": axis[best_i] if best_i is not None else None,
            "best_day_revenue": rev[best_i] if best_i is not None else 0,
            "avg_daily_revenue": round(rev_total / n) if n else 0,
            "wholesale_cost": wholesale,
            "previous_total_revenue": sold_prev_total,
        },
        "funnel": {
            "created": created_total,
            "paid": paid_ever,
            "completed": completed,
            "failed": sum(v for k, v in status_cnt.items() if k in ("payment_failed", "provisioning_failed")),
            "cancelled": status_cnt.get("cancelled", 0),
            "provisioning_success_pct": _ratio(prov_ok, prov_ok + prov_bad),
            "previous": {"created": created_prev_total, "paid": paid_ever_p, "completed": completed_p},
        },
        "orders_by_status": [{"status": k, "count": v} for k, v in status_cnt.most_common()],
        "by_method": _split(by_method),
        "by_channel": _split(by_channel),
        "by_kind": _split(by_kind),
        "top_products": _top(by_product, "product_id"),
        "top_stores": _top(by_store, "store_id", with_wholesale=True),
        "payment_providers": provider_rows,
        "heatmap": {"weekday_hour": heat, "peak": _peak(heat), "week_starts": "monday"},
        "attention_orders": sum(v for k, v in status_cnt.items() if k in ATTENTION),
    }


def _peak(heat: list[list[int]]) -> dict | None:
    best = max(((d, h) for d in range(7) for h in range(24)), key=lambda x: heat[x[0]][x[1]])
    return {"weekday": best[0], "hour": best[1], "count": heat[best[0]][best[1]]} if heat[best[0]][best[1]] else None


async def _load(session: AsyncSession, since: dt.datetime, store_id: uuid.UUID | None):
    """Bounded row loads for [since, now]. The padding (1 day) keeps zone edges correct; the pure core filters exactly."""
    pad = since - dt.timedelta(days=1)
    q_o = (
        select(
            Order.created_at,
            Order.paid_at,
            Order.status,
            Order.total,
            Order.currency,
            Order.store_id,
            Order.product_id,
            Order.payment_method,
            Order.channel,
            Order.kind,
            Order.reseller_cost,
        )  # fmt: skip
        .where((Order.created_at >= pad) | (Order.paid_at >= pad))
        .order_by(Order.created_at.desc())
        .limit(MAX_ROWS + 1)
    )
    sale_at = func.coalesce(Payment.reviewed_at, Payment.created_at)
    q_p = (
        select(
            Payment.created_at,
            Payment.reviewed_at,
            Payment.status,
            Payment.amount,
            Payment.currency,
            Payment.provider,
            Payment.purpose,
            Payment.store_id,
        )  # fmt: skip
        .where(sale_at >= pad)
        .order_by(Payment.created_at.desc())
        .limit(MAX_ROWS + 1)
    )
    q_u = select(User.created_at).where(User.created_at >= pad, User.is_guest.is_(False)).limit(MAX_ROWS + 1)
    if store_id:
        q_o, q_p = q_o.where(Order.store_id == store_id), q_p.where(Payment.store_id == store_id)
    o_rows = (await session.execute(q_o)).all()
    p_rows = (await session.execute(q_p)).all()
    u_rows = (await session.scalars(q_u)).all()
    truncated = max(len(o_rows), len(p_rows), len(u_rows)) > MAX_ROWS
    orders = [OrderRow(r[0], r[1], r[2], int(r[3] or 0), r[4], str(r[5]), str(r[6]), r[7], r[8], r[9], r[10]) for r in o_rows[:MAX_ROWS]]
    pays = [PayRow(r[0], r[1], r[2], int(r[3] or 0), r[4], r[5], r[6], str(r[7])) for r in p_rows[:MAX_ROWS]]
    return orders, pays, list(u_rows[:MAX_ROWS]), truncated


async def _snapshot(session: AsyncSession, now: dt.datetime) -> dict:
    """Point-in-time operational numbers (not period based): VPN fleet, tickets, users."""
    vpn_status = dict((await session.execute(select(VpnAccount.status, func.count(VpnAccount.id)).group_by(VpnAccount.status))).all())
    soon = now + dt.timedelta(days=7)
    expiring = (
        await session.scalar(
            select(func.count(VpnAccount.id)).where(
                VpnAccount.status == "active",
                VpnAccount.expires_at.is_not(None),
                VpnAccount.expires_at >= now,
                VpnAccount.expires_at <= soon,
            )
        )
        or 0
    )
    used, limit = (
        await session.execute(
            select(
                func.coalesce(func.sum(VpnAccount.traffic_used_bytes), 0), func.coalesce(func.sum(VpnAccount.traffic_limit_bytes), 0)
            ).where(VpnAccount.status == "active")
        )
    ).one()
    tickets = dict((await session.execute(select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status))).all())
    users_total = await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True), User.is_guest.is_(False))) or 0
    return {
        "vpn": {
            "by_status": [{"status": k, "count": int(v)} for k, v in sorted(vpn_status.items(), key=lambda kv: -kv[1])],
            "active": int(vpn_status.get("active", 0)),
            "expiring_7d": int(expiring),
            "traffic_used_bytes": int(used),
            "traffic_limit_bytes": int(limit),
        },
        "tickets": {"by_status": [{"status": k, "count": int(v)} for k, v in tickets.items()], "open": int(tickets.get("open", 0))},
        "users_total": int(users_total),
    }


async def _names(session: AsyncSession, payload: dict) -> None:
    pids = {uuid.UUID(r["product_id"]) for r in payload["top_products"]}
    sids = {uuid.UUID(r["store_id"]) for r in payload["top_stores"]}
    products = {p.id: p.name for p in (await session.scalars(select(Product).where(Product.id.in_(pids)))).all()} if pids else {}
    stores = {s.id: s for s in (await session.scalars(select(Store).where(Store.id.in_(sids)))).all()} if sids else {}
    for r in payload["top_products"]:
        r["name"] = products.get(uuid.UUID(r["product_id"])) or "محصول حذف‌شده"
    for r in payload["top_stores"]:
        s = stores.get(uuid.UUID(r["store_id"]))
        r["name"], r["kind"] = (s.name, s.kind) if s else ("فروشگاه حذف‌شده", "unknown")


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
