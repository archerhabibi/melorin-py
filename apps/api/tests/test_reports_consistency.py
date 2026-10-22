"""M6.9: reports API consistency (404, typed ids, date filter, pagination, population, time zone)."""

import datetime as dt
import uuid

import pytest

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db
from melorin.core.errors import AppError
from melorin.modules.admin import timeseries as ts
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.modules.reports import router as reports
from melorin.kernel.models.stores import Store

NOW = dt.datetime(2026, 10, 13, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
async def sdb(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/m6.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=[Payment.__table__, Order.__table__, Store.__table__]))
    yield
    await db.engine().dispose()


def _pay(store_id, cur, amount, when, status="succeeded"):
    return Payment(
        user_id=uuid.uuid4(),
        store_id=store_id,
        purpose="order",
        provider="manual_card",
        amount=amount,
        currency=cur,
        status=status,
        created_at=when,
    )


def _order(n, when, status):
    return Order(
        number=n,
        user_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        status=status,
        payment_method="wallet",
        currency="IRT",
        unit_price=1,
        total=1,
        pricing_snapshot={},
        product_snapshot={},
        created_at=when,
    )


# ---- time zone -------------------------------------------------------------------------------


def test_resolve_zone_defaults_to_utc_and_rejects_unknown_names():
    assert ts.resolve_zone(None).key == "UTC" and ts.resolve_zone("").key == "UTC"
    assert ts.resolve_zone("Asia/Tehran").key == "Asia/Tehran"
    for bad in ("Mars/Olympus", "../etc/passwd", "x" * 60):
        with pytest.raises(ValueError):
            ts.resolve_zone(bad)


def test_axis_follows_the_requested_zone():
    late = dt.datetime(2026, 10, 13, 22, 0, tzinfo=dt.UTC)  # already 14 Oct 01:30 in Tehran
    assert ts.day_axis(7, late)[-1] == "2026-10-13"
    assert ts.day_axis(7, late, ts.resolve_zone("Asia/Tehran"))[-1] == "2026-10-14"


def test_postgres_zone_bucketing_uses_the_requested_zone():
    from sqlalchemy.dialects import postgresql

    expr = ts.local_day(Payment.created_at, "postgresql", "Asia/Tehran")
    compiled = expr.compile(dialect=postgresql.dialect())
    assert "timezone" in str(compiled).lower() and "Asia/Tehran" in compiled.params.values()


async def test_sale_late_in_the_utc_day_lands_on_the_local_day_in_tehran(sdb):
    sale = dt.datetime(2026, 10, 12, 23, 17, tzinfo=dt.UTC)  # 13 Oct 02:47 Tehran (UTC+3:30)
    async with db.session_factory()() as s:
        s.add_all([_pay(uuid.uuid4(), "IRT", 150000, sale), _order("T1", sale, "completed")])
        await s.commit()
        utc = await ts.build_timeseries(s, 7, NOW)
        teh = await ts.build_timeseries(s, 7, NOW, tz="Asia/Tehran")
    assert utc["timezone"] == "UTC" and teh["timezone"] == "Asia/Tehran"
    assert utc["payments"][0]["amounts"][-2] == 150000 and utc["payments"][0]["amounts"][-1] == 0
    assert teh["payments"][0]["amounts"][-1] == 150000 and teh["payments"][0]["amounts"][-2] == 0
    assert teh["orders"][-1] == 1 and sum(teh["orders"]) == 1


# ---- population ------------------------------------------------------------------------------


async def test_orders_series_counts_sold_orders_and_orders_all_counts_everything(sdb):
    statuses = ["completed", "paid", "provisioning_failed", "pending", "payment_failed", "cancelled", "refunded"]
    async with db.session_factory()() as s:
        s.add_all([_order(f"O{i}", NOW, st) for i, st in enumerate(statuses)])
        await s.commit()
        out = await ts.build_timeseries(s, 7, NOW)
    assert out["orders"][-1] == 3  # completed, paid, provisioning_failed (money received, not unwound)
    assert out["orders_all"][-1] == len(statuses)
    assert sum(out["orders"]) <= sum(out["orders_all"])


# ---- reports router ----------------------------------------------------------------------------


async def test_store_sales_unknown_store_is_404_not_an_empty_200(sdb):
    async with db.session_factory()() as s:
        with pytest.raises(AppError) as exc:
            await reports.store_sales(uuid.uuid4(), None, s)
    assert exc.value.status == 404 and exc.value.code == "NOT_FOUND"


def test_store_sales_takes_a_typed_store_id():
    import inspect

    assert inspect.signature(reports.store_sales).parameters["store_id"].annotation is uuid.UUID


async def test_payments_date_filter_and_pagination(sdb):
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    async with db.session_factory()() as s:
        s.add_all(
            [
                _pay(s1, "IRT", 100, dt.datetime(2026, 10, 1, 12, tzinfo=dt.UTC)),
                _pay(s1, "IRT", 200, dt.datetime(2026, 10, 10, 23, 59, tzinfo=dt.UTC)),
                _pay(s1, "IRT", 400, dt.datetime(2026, 10, 11, 0, 0, tzinfo=dt.UTC)),
                _pay(s2, "USD", 5, dt.datetime(2026, 10, 10, 8, tzinfo=dt.UTC)),
                _pay(s2, "USD", 999, dt.datetime(2026, 10, 10, 8, tzinfo=dt.UTC), status="failed"),
            ]
        )
        await s.commit()
        d = dt.date
        every = await reports.payment_totals(None, s, None, None, 100, 0)
        ranged = await reports.payment_totals(None, s, d(2026, 10, 10), d(2026, 10, 10), 100, 0)
        first = await reports.payment_totals(None, s, None, None, 1, 0)
        second = await reports.payment_totals(None, s, None, None, 1, 1)
        with pytest.raises(AppError) as exc:
            await reports.payment_totals(None, s, d(2026, 10, 12), d(2026, 10, 1), 100, 0)
    assert {(r["currency"], r["amount"]) for r in every} == {("IRT", 700), ("USD", 5)}
    assert {(r["currency"], r["amount"], r["count"]) for r in ranged} == {("IRT", 200, 1), ("USD", 5, 1)}
    assert len(first) == 1 and len(second) == 1 and first[0]["store_id"] != second[0]["store_id"]
    assert exc.value.status == 422 and exc.value.code == "INVALID_DATE_RANGE"


def test_payments_endpoint_bounds_are_declared():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(reports.router)
    params = {p["name"]: p for p in app.openapi()["paths"]["/reports/payments"]["get"]["parameters"]}
    assert {"date_from", "date_to", "limit", "offset"} <= set(params)
    assert params["limit"]["schema"]["maximum"] == 500 and params["limit"]["schema"]["default"] == 100
    assert params["offset"]["schema"]["minimum"] == 0
    sales = app.openapi()["paths"]["/reports/stores/{store_id}/sales"]["get"]["parameters"][0]
    assert sales["schema"]["format"] == "uuid"
