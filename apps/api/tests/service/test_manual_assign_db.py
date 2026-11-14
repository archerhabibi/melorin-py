"""PG-04 / decision 1: assigning a hand-made panel user to a store customer.

The zero-price ``manual`` order is NOT a sale: no revenue, no commission, no referral reward, no loyalty points, no return,
nothing in the orders topic. The panel is only read, never written; a panel that does not answer means nothing is created."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_store, make_user, open_schema_engine
from melorin.core import codes
from melorin.core.errors import AppError
from melorin.domain.order_kinds import MANUAL, NON_REVENUE_KINDS, is_revenue
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.stores import StoreMembership
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.vpn import Panel, PanelAdmin, PanelOrphan, VpnAccount
from melorin.modules.admin import panel_orphans
from melorin.modules.reports import timeseries
from melorin.modules.eventcenter import rules
from melorin.modules.referral import service as referral
from melorin.modules.reports import router as reports
from melorin.modules.vpn_accounts import inquiry, manual_assign, returns
from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError
from test_pasarguard_service_db import FakePanel, remote

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def maker(monkeypatch):
    counter = iter(range(1, 10_000))

    async def next_code(session, sequence):  # SQLite has no sequences: same 6-char shape, still unique
        return f"M{next(counter):05d}"

    monkeypatch.setattr(codes, "next_code", next_code)
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


async def seed(maker, *, orphan_status="open", owner="ml_main", admin_username="ml_main", member=True):
    async with maker() as s:
        store, customer, admin, product = (
            await make_store(s),
            await make_user(s),
            await make_user(s, super_admin=True),
            await make_product(s),
        )
        panel = Panel(name="pg", kind="mock", base_url="http://pg", is_enabled=True)
        s.add(panel)
        await s.flush()
        if admin_username:
            s.add(PanelAdmin(panel_id=panel.id, store_id=store.id, username=admin_username, status="active"))
        if member:
            s.add(StoreMembership(store_id=store.id, user_id=customer.id, role="customer", status="active"))
        orphan = PanelOrphan(panel_id=panel.id, username="hand_made", remote_id=7, owner_username=owner, status=orphan_status)
        s.add(orphan)
        await s.commit()
        return {
            "store": store.id,
            "customer": customer.id,
            "admin": admin.id,
            "product": product.id,
            "panel": panel.id,
            "orphan": orphan.id,
        }


def use(monkeypatch, fake):
    monkeypatch.setattr(manual_assign, "build_adapter", lambda panel: fake)


async def assign(maker, ids, **kw):
    async with maker() as s:
        admin = await s.get(User, ids["admin"])
        return await manual_assign.assign_orphan(
            s, admin=admin, orphan_id=ids["orphan"], store_id=ids["store"], user_id=ids["customer"], product_id=ids["product"], **kw
        )


# ------------------------------------------------------------------------------------------------------------- the rule itself
async def test_the_rule_is_one_set_of_kinds():
    assert NON_REVENUE_KINDS == {"test", "manual"}
    assert not is_revenue("manual") and not is_revenue("test")
    assert is_revenue("purchase") and is_revenue("renewal")


# ------------------------------------------------------------------------------------------------------------- happy path
async def test_assign_creates_account_and_a_zero_price_manual_order(maker, monkeypatch):
    ids = await seed(maker)
    use(monkeypatch, FakePanel([remote("hand_made", ref="7", expire_days=20, limit=5 * 2**30, used=1 * 2**30)]))
    r = await assign(maker, ids, note="  from the old bot  ")
    assert r.owner_matches is True and r.expected_owner == "ml_main"
    async with maker() as s:
        order = await s.get(Order, r.order.id)
        assert (order.kind, order.total, order.unit_price, order.discount, order.reseller_cost) == (MANUAL, 0, 0, 0, None)
        assert (order.status, order.payment_method, order.channel) == ("completed", "free", "admin")
        assert order.pricing_snapshot["revenue"] == "excluded" and order.vpn_account_id == r.account.id
        acc = await s.get(VpnAccount, r.account.id)
        assert (acc.username, acc.user_id, acc.store_id, acc.order_id, acc.panel_ref, acc.is_test) == (
            "hand_made",
            ids["customer"],
            ids["store"],
            order.id,
            "7",
            False,
        )
        assert acc.sold_traffic_bytes == 5 * 2**30 and acc.sold_expires_at is not None  # the entitlement is the panel's reading now
        assert acc.delivery_snapshot and acc.last_synced_at and acc.status == "active"
        orphan = await s.get(PanelOrphan, ids["orphan"])
        assert orphan.status == "gone" and str(acc.id) in orphan.note
        audit = (await s.scalars(select(AuditEvent).where(AuditEvent.action == "vpn_account.manual_assigned"))).one()
        assert audit.data["owner_matches"] is True and "loyalty" in audit.data["excluded_from"] and audit.data["note"] == "from the old bot"


async def test_a_manual_orphan_can_be_assigned_and_an_ignored_one_must_be_reopened(maker, monkeypatch):
    ids = await seed(maker, orphan_status="manual")
    use(monkeypatch, FakePanel([remote("hand_made", ref="7")]))
    await assign(maker, ids)
    ids2 = await seed(maker, orphan_status="ignored")
    with pytest.raises(AppError) as err:
        await assign(maker, ids2)
    assert err.value.code == "ORPHAN_NOT_ASSIGNABLE"


async def test_owner_mismatch_is_reported_before_it_happens_and_nothing_is_written_to_the_panel(maker, monkeypatch):
    ids = await seed(maker, owner="someone_else")
    fake = FakePanel([remote("hand_made", ref="7", owner="someone_else")])
    use(monkeypatch, fake)
    r = await assign(maker, ids)
    assert r.owner_matches is False and r.expected_owner == "ml_main"
    assert list(fake.users) == ["hand_made"]  # the panel is untouched


# ------------------------------------------------------------------------------------------------------------- refusals
async def test_a_panel_that_does_not_answer_creates_nothing(maker, monkeypatch):
    ids = await seed(maker)

    class Down(FakePanel):
        async def get_account(self, username):
            raise PanelError(ErrorKind.TRANSIENT, "down")

    use(monkeypatch, Down())
    with pytest.raises(inquiry.PanelUnavailable):
        await assign(maker, ids)
    async with maker() as s:
        assert await s.scalar(select(func.count()).select_from(Order).where(Order.kind == MANUAL)) == 0
        assert await s.scalar(select(func.count()).select_from(VpnAccount)) == 0
        assert (await s.get(PanelOrphan, ids["orphan"])).status == "open"


async def test_a_user_that_vanished_from_the_panel_is_refused(maker, monkeypatch):
    ids = await seed(maker)
    use(monkeypatch, FakePanel([]))
    with pytest.raises(AppError) as err:
        await assign(maker, ids)
    assert err.value.code == "ORPHAN_GONE"


async def test_the_customer_must_be_an_active_member_of_that_store(maker, monkeypatch):
    ids = await seed(maker, member=False)
    use(monkeypatch, FakePanel([remote("hand_made", ref="7")]))
    with pytest.raises(AppError) as err:
        await assign(maker, ids)
    assert err.value.code == "NOT_A_MEMBER"


async def test_a_test_product_is_not_a_valid_package(maker, monkeypatch):
    ids = await seed(maker)
    async with maker() as s:
        p = await s.get(Product, ids["product"])
        p.is_test = True
        await s.commit()
    use(monkeypatch, FakePanel([remote("hand_made", ref="7")]))
    with pytest.raises(AppError):
        await assign(maker, ids)


async def test_the_same_panel_user_cannot_be_assigned_twice(maker, monkeypatch):
    ids = await seed(maker)
    use(monkeypatch, FakePanel([remote("hand_made", ref="7")]))
    await assign(maker, ids)
    with pytest.raises(AppError) as err:  # now ``gone`` (Melorin knows it)
        await assign(maker, ids)
    assert err.value.code in ("ORPHAN_GONE", "USERNAME_TAKEN")


# ------------------------------------------------------------------------------------------------------------- exclusions
async def _assigned(maker, monkeypatch):
    ids = await seed(maker)
    use(monkeypatch, FakePanel([remote("hand_made", ref="7")]))
    return ids, await assign(maker, ids)


async def test_not_in_the_store_sales_report(maker, monkeypatch):
    ids, r = await _assigned(maker, monkeypatch)
    async with maker() as s:
        from melorin.kernel.models.stores import Store

        store, product, user = await s.get(Store, ids["store"]), await s.get(Product, ids["product"]), await s.get(User, ids["customer"])
        await make_order(s, user=user, store=store, product=product, total=1000, status="completed")
        await s.commit()
        out = await reports.store_sales(ids["store"], None, s)
    rows = {o["status"]: (o["count"], o["total"]) for o in out["orders"]}
    assert rows == {"completed": (1, 1000)}  # the manual order (completed, 0) is not counted as an order


async def test_not_in_the_timeseries_counts(maker, monkeypatch):
    _, _ = await _assigned(maker, monkeypatch)
    async with maker() as s:
        data = await timeseries.build_timeseries(s, days=7)
    assert sum(data["orders_all"]) == 0 and sum(data["orders"]) == 0  # a completed order would otherwise show as 1 sold


async def test_no_referral_reward_and_not_store_history(maker, monkeypatch):
    ids, r = await _assigned(maker, monkeypatch)
    async with maker() as s:
        assert await referral.has_store_history(s, ids["store"], ids["customer"]) is False  # still "new here" for new-customer rules
        await referral.on_order_completed(s, r.order.id)  # total 0 and not a revenue kind: returns without any commission
        from melorin.kernel.models.referral import Commission

        assert await s.scalar(select(func.count()).select_from(Commission)) == 0


async def test_no_loyalty_points(maker, monkeypatch):
    ids, r = await _assigned(maker, monkeypatch)
    from melorin.kernel.models.loyalty import LoyaltyAccount
    from melorin.kernel.models.stores import Store
    from melorin.modules.loyalty import service as loyalty

    async with maker() as s:
        await loyalty.ensure_program(s, await s.get(Store, ids["store"]))
        await loyalty.on_order_completed(s, r.order.id)
        assert await s.scalar(select(func.count()).select_from(LoyaltyAccount)) == 0


async def test_no_return_no_event_in_the_orders_topic(maker, monkeypatch):
    ids, r = await _assigned(maker, monkeypatch)
    async with maker() as s:
        order, acc = await s.get(Order, r.order.id), await s.get(VpnAccount, r.account.id)
        verdict = returns.evaluate(acc, order, renewed=False, returns_last_day=0, used_bytes=0)
        assert verdict.ok is False
        assert await rules._order_rule(s, "x", {"order_id": str(order.id)}) is None


async def test_the_route_is_registered_and_documented():
    paths = {r.path for r in panel_orphans.router.routes}
    assert "/admin/panel-orphans/{orphan_id}/assign" in paths
    assert set(manual_assign.EXCLUDED_FROM) >= {"sales", "commission", "referral", "loyalty"}
