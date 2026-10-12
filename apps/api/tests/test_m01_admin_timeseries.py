import datetime as dt
import uuid
from pathlib import Path

import pytest

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db
from melorin.modules.admin import timeseries as ts
from melorin.modules.orders.models import Order
from melorin.modules.payments.models import Payment

NOW = dt.datetime(2026, 10, 13, 15, 0, tzinfo=dt.UTC)


def test_axis_is_continuous_utc_and_ends_today():
    axis = ts.day_axis(7, NOW)
    assert axis[0] == "2026-10-07" and axis[-1] == "2026-10-13" and len(axis) == 7


def test_fill_zero_fills_and_ignores_out_of_range_days():
    axis = ts.day_axis(7, NOW)
    assert ts.fill(axis, [("2026-10-09", 5), ("2026-10-13", 2), ("2020-01-01", 99)]) == [0, 0, 5, 0, 0, 0, 2]


def test_route_is_admin_only_and_bounded():
    src = (Path(__file__).parents[1] / "melorin/modules/admin/router.py").read_text()
    assert '@router.get("/reports/timeseries")' in src and "_: AdminUser" in src.split("reports/timeseries")[1][:200]
    assert "ge=7, le=90" in src


@pytest.fixture
async def sdb(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/ts.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=[Payment.__table__, Order.__table__]))
    yield
    await db.engine().dispose()


def _pay(cur, amount, status, when):
    return Payment(user_id=uuid.uuid4(), store_id=uuid.uuid4(), purpose="order", provider="manual_card", amount=amount, currency=cur, status=status, created_at=when)


def _order(n, when):
    return Order(number=n, user_id=uuid.uuid4(), store_id=uuid.uuid4(), product_id=uuid.uuid4(), status="paid", payment_method="wallet", currency="IRT", unit_price=1, total=1, pricing_snapshot={}, product_snapshot={}, created_at=when)


async def test_series_is_currency_separated_and_counts_only_succeeded(sdb):
    d = lambda n: NOW - dt.timedelta(days=n)  # noqa: E731
    async with db.session_factory()() as s:
        s.add_all([
            _pay("IRT", 1000, "succeeded", d(0)), _pay("IRT", 500, "succeeded", d(0)), _pay("IRT", 700, "failed", d(0)),
            _pay("USD", 9, "succeeded", d(2)), _pay("IRT", 300, "succeeded", d(40)),
            _order("A1", d(0)), _order("A2", d(1)), _order("A3", d(1)), _order("OLD", d(60)),
        ])
        await s.commit()
        out = await ts.build_timeseries(s, 7, NOW)
    assert out["days"][-1] == "2026-10-13" and out["currency_safe"] is True
    by = {p["currency"]: p for p in out["payments"]}
    assert set(by) == {"IRT", "USD"}
    assert by["IRT"]["amounts"][-1] == 1500 and by["IRT"]["counts"][-1] == 2 and sum(by["IRT"]["amounts"]) == 1500
    assert by["USD"]["amounts"][-3] == 9 and sum(by["USD"]["amounts"]) == 9
    assert out["orders"][-1] == 1 and out["orders"][-2] == 2 and sum(out["orders"]) == 3
