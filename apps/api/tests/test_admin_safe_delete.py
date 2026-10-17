"""DELETE for products, panels, servers and sales bundles: real delete when unused, 409 + reason once history exists."""
import types
import uuid

import pytest
from sqlalchemy import func, select

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db
from melorin.core.errors import AppError
from melorin.modules.admin import router as r
from melorin.modules.catalog.models import Coupon, Product, StoreBundlePrice, StoreProduct
from melorin.modules.orders.models import Order
from melorin.modules.referral.models import CommissionRule
from melorin.modules.system.models import AuditEvent
from melorin.modules.vpn.models import Panel, Server, VpnAccount
from melorin.modules.vpn.panel_groups import PanelGroup, PanelGroupMember, BundleProduct, StorePanelGroup

ADMIN = types.SimpleNamespace(id=uuid.uuid4())


@pytest.fixture
async def session(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/delete.db")
    async with db.engine().begin() as conn:
        tables = [m.__table__ for m in (Panel, Server, VpnAccount, Product, StoreProduct, Coupon, Order, CommissionRule, AuditEvent, PanelGroup, PanelGroupMember, StorePanelGroup, BundleProduct, StoreBundlePrice)]
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=tables))
    async with db.session_factory()() as s:
        yield s
    await db.engine().dispose()


async def _add(session, obj):
    session.add(obj)
    await session.flush()
    return obj


def _product(code="P30", **kw):
    return Product(code=code, name=f"plan {code}", duration_days=30, traffic_gb=10, main_price=1, reseller_price=1, currency="IRT", **kw)


async def _panel(session, name="P1"):
    return await _add(session, Panel(name=name, kind="mock", base_url="https://p.example.com", config={}))


async def _server(session, panel, name="S1", **kw):
    return await _add(session, Server(name=name, panel_id=panel.id, capacity=10, **kw))


async def _account(session, product, panel=None, server=None):
    return await _add(session, VpnAccount(username=f"u{uuid.uuid4().hex[:8]}", user_id=uuid.uuid4(), store_id=uuid.uuid4(), order_id=uuid.uuid4(),
                                          product_id=product.id, server_id=server.id if server else None, panel_id=panel.id if panel else None, status="active"))


async def _order(session, product, **kw):
    return await _add(session, Order(number=uuid.uuid4().hex[:6], user_id=uuid.uuid4(), store_id=uuid.uuid4(), product_id=product.id, status="completed",
                                     payment_method="wallet", currency="IRT", unit_price=1, total=1, pricing_snapshot={}, product_snapshot={}, **kw))


async def _count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


async def _refused(coro, code):
    with pytest.raises(AppError) as e:
        await coro
    assert e.value.status == 409 and e.value.code == code
    return e.value


async def _audited(session, action):
    return (await session.scalars(select(AuditEvent).where(AuditEvent.action == action))).all()


# ---------- products ----------
async def test_unused_product_is_deleted_with_its_store_availability_and_audited(session):
    p = await _add(session, _product())
    await _add(session, StoreProduct(product_id=p.id, store_id=uuid.uuid4()))
    await session.commit()
    assert await r.delete_product(p.id, ADMIN, session) == {"ok": True}
    assert await _count(session, Product) == 0 and await _count(session, StoreProduct) == 0
    assert len(await _audited(session, "product.deleted")) == 1


async def test_product_with_orders_or_accounts_is_refused_and_kept(session):
    p = await _add(session, _product())
    await _order(session, p)
    await _account(session, p)
    await session.commit()
    e = await _refused(r.delete_product(p.id, ADMIN, session), "PRODUCT_HAS_HISTORY")
    assert e.details == {"orders": 1, "accounts": 1} and "غیرفعال" in e.message
    assert await _count(session, Product) == 1 and not await _audited(session, "product.deleted")


async def test_product_still_referenced_by_a_server_coupon_or_rule_is_refused(session):
    pan = await _panel(session)
    p = await _add(session, _product())
    srv = await _server(session, pan, product_codes=[p.code])
    await session.commit()
    e = await _refused(r.delete_product(p.id, ADMIN, session), "PRODUCT_USED_BY_SERVERS")
    assert e.details == {"servers": ["S1"]}
    srv.product_codes = None
    c = await _add(session, Coupon(code="OFF", owner_key="admin", scope="domain", product_ids=[str(p.id)]))
    await session.commit()
    await _refused(r.delete_product(p.id, ADMIN, session), "PRODUCT_USED_BY_COUPONS")
    c.product_ids = None
    await _add(session, CommissionRule(store_id=uuid.uuid4(), product_id=p.id, kind="commission", model="fixed", value=1))
    await session.commit()
    await _refused(r.delete_product(p.id, ADMIN, session), "PRODUCT_USED_BY_COMMISSION_RULES")
    assert await _count(session, Product) == 1


async def test_delete_unknown_product_is_404(session):
    with pytest.raises(AppError) as e:
        await r.delete_product(uuid.uuid4(), ADMIN, session)
    assert e.value.status == 404


# ---------- servers ----------
async def test_empty_server_is_deleted_but_one_with_accounts_is_not(session):
    pan = await _panel(session)
    p = await _add(session, _product())
    used, empty = await _server(session, pan, "used"), await _server(session, pan, "empty")
    await _account(session, p, pan, used)
    await session.commit()
    e = await _refused(r.delete_server(used.id, ADMIN, session), "SERVER_HAS_ACCOUNTS")
    assert e.details == {"accounts": 1}
    assert await r.delete_server(empty.id, ADMIN, session) == {"ok": True}
    left = (await session.scalars(select(Server.name))).all()
    assert left == ["used"] and len(await _audited(session, "server.deleted")) == 1


# ---------- panels ----------
async def test_unused_panel_is_deleted_with_its_empty_servers_and_group_memberships(session):
    pan, keep = await _panel(session), await _panel(session, "P2")
    await _server(session, pan, "a")
    await _server(session, pan, "b")
    g = await _add(session, PanelGroup(name="auto", selection_mode="automatic"))
    await _add(session, PanelGroupMember(panel_group_id=g.id, panel_id=pan.id))
    await _add(session, PanelGroupMember(panel_group_id=g.id, panel_id=keep.id, sort=1))
    await session.commit()
    out = await r.delete_panel(pan.id, ADMIN, session)
    assert out == {"ok": True, "servers_deleted": 2, "groups_left": 1}
    assert [x.id for x in (await session.scalars(select(Panel))).all()] == [keep.id]
    assert await _count(session, Server) == 0
    assert [m.panel_id for m in (await session.scalars(select(PanelGroupMember))).all()] == [keep.id]
    assert len(await _audited(session, "panel.deleted")) == 1


async def test_panel_with_accounts_or_orders_is_refused(session):
    pan = await _panel(session)
    srv = await _server(session, pan)
    p = await _add(session, _product())
    await _account(session, p, server=srv)  # linked only through its server
    await session.commit()
    await _refused(r.delete_panel(pan.id, ADMIN, session), "PANEL_HAS_HISTORY")
    other = await _panel(session, "P2")
    await _order(session, p, selected_panel_id=other.id)
    await session.commit()
    e = await _refused(r.delete_panel(other.id, ADMIN, session), "PANEL_HAS_HISTORY")
    assert e.details == {"accounts": 0, "orders": 1}
    assert await _count(session, Panel) == 2 and await _count(session, Server) == 1


async def test_panel_that_is_the_last_member_of_a_manual_group_is_refused(session):
    pan = await _panel(session)
    g = await _add(session, PanelGroup(name="manual-de", selection_mode="manual"))
    await _add(session, PanelGroupMember(panel_group_id=g.id, panel_id=pan.id))
    await session.commit()
    e = await _refused(r.delete_panel(pan.id, ADMIN, session), "PANEL_LAST_IN_MANUAL_GROUP")
    assert e.details == {"group": "manual-de"}
    assert await _count(session, Panel) == 1 and await _count(session, PanelGroupMember) == 1


# ---------- sales bundles ----------
async def test_unused_group_is_deleted_with_members_and_store_links(session):
    pan = await _panel(session)
    g = await _add(session, PanelGroup(name="g"))
    await _add(session, PanelGroupMember(panel_group_id=g.id, panel_id=pan.id))
    await _add(session, StorePanelGroup(store_id=uuid.uuid4(), panel_group_id=g.id))
    await _add(session, StoreBundlePrice(store_id=uuid.uuid4(), panel_group_id=g.id, product_id=uuid.uuid4(), customer_price=1000))
    await session.commit()
    assert await r.delete_panel_group(g.id, ADMIN, session) == {"ok": True}
    assert [await _count(session, m) for m in (PanelGroup, PanelGroupMember, StorePanelGroup, BundleProduct, StoreBundlePrice)] == [0, 0, 0, 0, 0]
    assert await _count(session, Panel) == 1  # panels themselves are untouched
    assert len(await _audited(session, "panel_group.deleted")) == 1


async def test_group_that_is_a_products_default_or_has_orders_is_refused(session):
    g = await _add(session, PanelGroup(name="g"))
    p = await _add(session, _product(default_panel_group_id=g.id))
    await session.commit()
    e = await _refused(r.delete_panel_group(g.id, ADMIN, session), "PANEL_GROUP_IN_USE")
    assert e.details == {"products": ["plan P30"]}
    p.default_panel_group_id = None
    await _order(session, p, panel_group_id=g.id)
    await session.commit()
    await _refused(r.delete_panel_group(g.id, ADMIN, session), "PANEL_GROUP_HAS_HISTORY")
    assert await _count(session, PanelGroup) == 1


PATHS = ("products/{product_id}", "panels/{panel_id}", "servers/{server_id}", "panel-groups/{panel_group_id}")


def test_delete_routes_are_registered_on_the_admin_router():
    have = {(m, x.path) for x in r.router.routes for m in getattr(x, "methods", ())}
    for path in PATHS:
        assert ("DELETE", f"/admin/{path}") in have


async def test_delete_routes_reject_anonymous_callers():
    import httpx
    from melorin.app import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for path in PATHS:
            res = await c.delete("/api/v1/admin/" + path.split("/")[0] + f"/{uuid.uuid4()}")
            assert res.status_code in (401, 403), path
