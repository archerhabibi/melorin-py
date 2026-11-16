"""reports: analytics_compute (see ``analytics.py`` for the facade)."""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any, NamedTuple

from melorin.domain.order_state import OrderStatus
from melorin.domain.timeutil import aware as _aware
from melorin.modules.reports.timeseries import SOLD_STATUSES

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


def _day(value: dt.datetime, zone: dt.tzinfo) -> str:
    return _aware(value).astimezone(zone).date().isoformat()


def pct_change(cur: float, prev: float) -> float | None:
    """Relative change in percent; ``None`` when there is no previous value to compare with."""
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _kpi(cur: float, prev: float, spark: Sequence[float] | None = None) -> dict:
    out: dict[str, Any] = {"value": cur, "previous": prev, "delta_pct": pct_change(cur, prev)}
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

    provider_rows: list[dict[str, Any]] = []
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
