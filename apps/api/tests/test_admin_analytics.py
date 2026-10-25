"""Reports & charts: the pure analytics core and the ``/admin/reports/analytics`` HTTP surface."""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

import pytest

from _db import make_order, make_product, make_store, make_user
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.modules.admin import analytics as an
from melorin.modules.admin.timeseries import day_axis

ADMIN = "/api/v1/admin"
NOW = dt.datetime(2026, 10, 13, 15, 0, tzinfo=dt.UTC)
S1, S2, P1, P2 = (str(uuid.uuid4()) for _ in range(4))


def _axes(days=7, zone=dt.UTC):
    return day_axis(days, NOW, zone), day_axis(days, NOW - dt.timedelta(days=days), zone)


def _o(when, status="completed", total=1000, cur="IRT", store=S1, product=P1, method="wallet", channel="web", kind="purchase", cost=None):
    return an.OrderRow(when, when, status, total, cur, store, product, method, channel, kind, cost)


def _p(when, status="succeeded", amount=500, cur="IRT", provider="manual_card"):
    return an.PayRow(when, None, status, amount, cur, provider, "wallet_topup", S1)


def _run(orders=(), pays=(), users=(), days=7, zone=dt.UTC, currency=None):
    axis, prev = _axes(days, zone)
    return an.compute_analytics(list(orders), list(pays), list(users), axis=axis, prev_axis=prev, zone=zone, currency=currency)


def at(day, hour=12):
    return dt.datetime(2026, 10, day, hour, 0, tzinfo=dt.UTC)


# ---- pure core ---------------------------------------------------------------------------------------------------


def test_empty_database_gives_a_complete_zero_payload():
    r = _run()
    assert r["currency"] == "IRT" and r["kpis"]["revenue"]["value"] == 0 and r["kpis"]["revenue"]["delta_pct"] is None
    assert len(r["series"]["revenue"]) == 7 and sum(r["series"]["revenue"]) == 0
    assert r["heatmap"]["peak"] is None and r["top_products"] == [] and r["funnel"]["created"] == 0


def test_revenue_counts_only_sold_orders_and_compares_with_previous_period():
    cur = [_o(at(13), total=3000), _o(at(12), "paid", 2000), _o(at(11), "cancelled", 9999), _o(at(10), "refunded", 5000)]
    prev = [_o(at(5), total=1000), _o(at(4), total=1000)]  # previous 7-day window: Oct 0-6
    r = _run(cur + prev)
    k = r["kpis"]
    assert k["revenue"]["value"] == 5000 and k["revenue"]["previous"] == 2000 and k["revenue"]["delta_pct"] == 150.0
    assert k["orders_sold"]["value"] == 2 and k["avg_order_value"]["value"] == 2500
    assert r["series"]["revenue"][-1] == 3000 and r["series"]["cumulative_revenue"][-1] == 5000
    assert r["highlights"]["best_day"] == "2026-10-13" and r["highlights"]["best_day_revenue"] == 3000


def test_money_is_never_mixed_across_currencies_and_default_is_the_top_seller():
    rows = [_o(at(13), total=100, cur="IRT"), _o(at(12), total=700, cur="USD"), _o(at(11), total=50, cur="IRT")]
    r = _run(rows)
    assert r["currency"] == "USD" and r["currencies"] == ["USD", "IRT"] and r["kpis"]["revenue"]["value"] == 700
    assert _run(rows, currency="IRT")["kpis"]["revenue"]["value"] == 150
    assert _run(rows, currency="EUR")["currency"] == "USD"  # unknown currency falls back instead of returning zeros


def test_funnel_conversion_and_provisioning_success_use_orders_created_in_the_period():
    statuses = ["completed", "completed", "completed", "provisioning_failed", "payment_failed", "cancelled", "refunded"]
    r = _run([_o(at(12), s) for s in statuses])
    f = r["funnel"]
    # paid = completed x3 + provisioning_failed (money was received) + refunded (was paid, then unwound)
    assert f["created"] == 7 and f["paid"] == 5 and f["completed"] == 3
    assert f["failed"] == 2 and f["cancelled"] == 1 and f["provisioning_success_pct"] == 75.0
    assert r["kpis"]["conversion_pct"]["value"] == round(5 / 7 * 100, 1)
    assert r["kpis"]["refunds"]["count"] == 1 and r["attention_orders"] == 2


def test_breakdowns_top_lists_and_wholesale():
    rows = [
        _o(at(13), total=500, store=S1, product=P1, method="wallet", channel="telegram"),
        _o(at(13), total=900, store=S2, product=P2, method="manual_card", cost=600),
        _o(at(12), total=900, store=S2, product=P2, method="manual_card", cost=600),
    ]
    r = _run(rows)
    assert r["top_products"][0] == {"product_id": P2, "count": 2, "revenue": 1800}
    assert r["top_stores"][0]["store_id"] == S2 and r["top_stores"][0]["wholesale"] == 1200
    assert [m["key"] for m in r["by_method"]] == ["manual_card", "wallet"]
    assert {c["key"] for c in r["by_channel"]} == {"telegram", "web"}
    assert r["highlights"]["wholesale_cost"] == 1200


def test_cash_in_providers_and_success_rate():
    pays = [
        _p(at(13)),
        _p(at(13), amount=700),
        _p(at(12), "failed"),
        _p(at(12), "awaiting_review"),
        _p(at(11), amount=900, provider="zarinpal"),
    ]
    r = _run(pays=pays)
    assert r["kpis"]["cash_in"]["value"] == 2100 and r["series"]["cash_in_count"][-1] == 2
    by = {x["provider"]: x for x in r["payment_providers"]}
    assert by["manual_card"]["succeeded"] == 2 and by["manual_card"]["failed"] == 1 and by["manual_card"]["awaiting_review"] == 1
    assert by["manual_card"]["success_rate"] == round(2 / 3 * 100, 1) and by["zarinpal"]["success_rate"] == 100.0


def test_new_users_series():
    r = _run(users=[at(13), at(13, 1), at(10), at(2)])  # the Oct 2 user falls in the previous window
    assert r["series"]["new_users"][-1] == 2 and r["kpis"]["new_users"]["value"] == 3 and r["kpis"]["new_users"]["previous"] == 1


def test_heatmap_uses_the_local_time_zone():
    tehran = ZoneInfo("Asia/Tehran")  # UTC+3:30: 21:00 UTC on Mon Oct 12 is 00:30 on Tue Oct 13 in Tehran
    when = dt.datetime(2026, 10, 12, 21, 0, tzinfo=dt.UTC)
    utc = _run([_o(when)])["heatmap"]["peak"]
    local = _run([_o(when)], zone=tehran)
    assert (utc["weekday"], utc["hour"]) == (0, 21)
    assert (local["heatmap"]["peak"]["weekday"], local["heatmap"]["peak"]["hour"]) == (1, 0)
    assert local["series"]["orders"][-1] == 1  # bucketed into Oct 13 locally


def test_naive_datetimes_from_sqlite_are_treated_as_utc():
    r = _run([_o(at(13).replace(tzinfo=None), total=10)])
    assert r["kpis"]["revenue"]["value"] == 10


def test_csv_sections_have_matching_headers_and_rows():
    r = _run([_o(at(13), total=500)])
    r["top_products"][0]["name"] = "plan"
    r["top_stores"] = [{"store_id": S1, "name": "main", "kind": "main", "count": 1, "revenue": 500, "wholesale": 0}]
    for section in an.CSV_SECTIONS:
        head, rows = an.to_csv_rows(r, section)
        assert rows and all(len(row) == len(head) for row in rows), section
    with pytest.raises(ValueError):
        an.to_csv_rows(r, "nope")


# ---- HTTP -----------------------------------------------------------------------------------------------------------


async def _admin(c, maker, email="root@example.com"):
    await add_user(maker, email=email, admin=True, totp=True)
    r = await c.post("/api/v1/auth/password/login", json={"email": email, "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.parametrize("path", ["/reports/analytics", "/reports/analytics.csv"])
async def test_analytics_is_closed_to_anonymous_callers(path):
    async with api_client() as (c, _maker, _):
        assert (await c.get(f"{ADMIN}{path}")).status_code == 401


async def test_analytics_end_to_end_with_store_filter_csv_and_validation():
    async with api_client() as (c, maker, main):
        async with maker() as s:
            shop = await make_store(s, kind="reseller", currency="IRT", slug="paris")
            shop.name = "=HYPERLINK(1)"  # a hostile store name must not become a spreadsheet formula
            user, product = await make_user(s), await make_product(s, price=1000)
            a = await make_order(s, user=user, store=main, product=product, total=4000, status="completed")
            b = await make_order(s, user=user, store=shop, product=product, total=2500, status="completed", reseller_cost=1800)
            await make_order(s, user=user, store=main, product=product, total=999, status="cancelled")
            s.add(
                Payment(
                    user_id=user.id,
                    store_id=main.id,
                    purpose="wallet_topup",
                    provider="manual_card",
                    amount=4000,
                    currency="IRT",
                    status="succeeded",
                )
            )
            await s.commit()
            main_id, shop_id = str(main.id), str(shop.id)
        h = await _admin(c, maker)

        r = await c.get(f"{ADMIN}/reports/analytics?days=30&tz=Asia/Tehran", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["currency"] == "IRT" and body["kpis"]["revenue"]["value"] == 6500 and body["kpis"]["orders_sold"]["value"] == 2
        assert body["kpis"]["cash_in"]["value"] == 4000 and body["funnel"]["created"] == 3 and body["funnel"]["cancelled"] == 1
        assert body["period"]["timezone"] == "Asia/Tehran" and len(body["days"]) == 30 and body["truncated"] is False
        names = {x["store_id"]: x for x in body["top_stores"]}
        assert names[shop_id]["kind"] == "reseller" and names[shop_id]["wholesale"] == 1800 and names[main_id]["revenue"] == 4000
        assert body["top_products"][0]["name"] == "plan" and "vpn" in body and "tickets" in body and body["currency_safe"] is True

        only = (await c.get(f"{ADMIN}/reports/analytics?store_id={shop_id}", headers=h)).json()
        assert only["kpis"]["revenue"]["value"] == 2500 and only["scope"]["store_id"] == shop_id

        csv = await c.get(f"{ADMIN}/reports/analytics.csv?section=stores&days=30", headers=h)
        assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
        assert csv.content.startswith(b"\xef\xbb\xbf") and "'=HYPERLINK(1)" in csv.text and "\n=HYPERLINK" not in csv.text
        assert (await c.get(f"{ADMIN}/reports/analytics.csv?section=daily", headers=h)).text.count("\n") >= 31

        assert (await c.get(f"{ADMIN}/reports/analytics?tz=Mars/Base", headers=h)).status_code == 422
        assert (await c.get(f"{ADMIN}/reports/analytics?days=3", headers=h)).status_code == 422
        assert (await c.get(f"{ADMIN}/reports/analytics?store_id=not-a-uuid", headers=h)).status_code == 422
        assert (await c.get(f"{ADMIN}/reports/analytics.csv?section=secrets", headers=h)).status_code == 422
        assert a.id != b.id and isinstance(Order, type)
