"""Core allocation against a real (SQLite) database: order-time group rules, provisioning-time selection,
bulk load queries and the admin rules around a product's default group."""

import types
import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401  (registers every table)
from melorin.core.db import Base
from melorin.core.errors import AppError
from melorin.modules.admin.router import create_product, update_panel_group, update_product
from melorin.modules.admin.schemas import CreateProduct, ProductPatch, UpdatePanelGroup
from melorin.modules.catalog.models import Product
from melorin.modules.system.models import AuditEvent
from melorin.modules.vpn.adapters.base import PanelError
from melorin.modules.vpn.allocation import resolve_allocation, resolve_order_group
from melorin.modules.vpn.models import Panel, Server
from melorin.modules.vpn.panel_groups import PanelGroup, PanelGroupMember, PoolProduct, StorePanelGroup


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Tables are created one by one: the bot_store_bindings model declares one index twice, which
    # makes Base.metadata.create_all fail on SQLite (pre-existing, unrelated to allocation).
    for table in Base.metadata.sorted_tables:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync_conn, t=table: t.create(sync_conn, checkfirst=True))
        except Exception:
            pass
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        s.engine_ref = engine
        yield s
    await engine.dispose()


async def make_group(s, *, mode="automatic", enabled=True, panels=(("P1", "healthy"),), servers=(("S1", "P1", {}),), sales_limit=None):
    group = PanelGroup(name="G", selection_mode=mode, is_enabled=enabled, sales_limit=sales_limit)
    s.add(group)
    by_name = {}
    for name, health in panels:
        panel = Panel(name=name, kind="mock", base_url="http://x", is_enabled=True, health_status=health)
        s.add(panel)
        by_name[name] = panel
    await s.flush()
    for i, (name, _) in enumerate(panels):
        s.add(PanelGroupMember(panel_group_id=group.id, panel_id=by_name[name].id, sort=i))
    for sname, pname, kw in servers:
        s.add(Server(name=sname, panel_id=by_name[pname].id, **kw))
    await s.flush()
    return group, by_name


def make_product(group=None, code="10"):
    return Product(
        code=code, name="plan", duration_days=30, traffic_gb=10, main_price=1, reseller_price=1,
        default_panel_group_id=group.id if group else None,
    )


async def sell(s, product, *groups):
    """Persist the product and make every given pool sell it (what the admin does when filling a pool)."""
    s.add(product)
    await s.flush()
    for g in groups:
        s.add(PoolProduct(panel_group_id=g.id, product_id=product.id))
    await s.flush()
    return product


def order_for(group, *, kind="purchase", selected=None, store_id=None):
    return types.SimpleNamespace(panel_group_id=group.id if group else None, selected_panel_id=selected, store_id=store_id, kind=kind)


# ---------------------------------------------------------------- order-time rule (every channel)

async def test_product_default_group_applies_when_order_names_none(session):
    group, _ = await make_group(session)
    product = await sell(session, make_product(group), group)
    assert await resolve_order_group(session, store_id=None, product=product) == (group.id, None)


async def test_explicit_group_wins_over_product_default(session):
    default, _ = await make_group(session)
    other, _ = await make_group(session, panels=(("P9", "healthy"),), servers=(("S9", "P9", {}),))
    product = await sell(session, make_product(default), default, other)
    assert (await resolve_order_group(session, store_id=None, product=product, panel_group_id=other.id))[0] == other.id


async def test_there_is_no_pool_less_route(session):
    product = await sell(session, make_product(None))
    with pytest.raises(AppError) as e:
        await resolve_order_group(session, store_id=None, product=product, selected_panel_id=uuid.uuid4())
    assert e.value.code == "POOL_REQUIRED"


async def test_pool_that_does_not_sell_the_package_is_rejected(session):
    group, _ = await make_group(session)
    other, _ = await make_group(session, panels=(("P9", "healthy"),), servers=(("S9", "P9", {}),))
    product = await sell(session, make_product(group), group)  # sold in `group` only
    with pytest.raises(AppError) as e:
        await resolve_order_group(session, store_id=None, product=product, panel_group_id=other.id)
    assert e.value.code == "PRODUCT_NOT_IN_POOL"


async def test_manual_default_group_is_rejected_before_payment(session):
    group, _ = await make_group(session, mode="manual")
    with pytest.raises(AppError) as e:
        await resolve_order_group(session, store_id=None, product=make_product(group))
    assert e.value.code == "PANEL_GROUP_UNAVAILABLE"


async def test_disabled_group_is_rejected_before_payment(session):
    group, _ = await make_group(session, enabled=False)
    with pytest.raises(AppError):
        await resolve_order_group(session, store_id=None, product=make_product(group))


async def test_full_group_is_rejected_before_payment(session):
    group, _ = await make_group(session, sales_limit=1)
    group.sold_count = 1
    await session.flush()
    with pytest.raises(AppError):
        await resolve_order_group(session, store_id=None, product=make_product(group))


async def test_store_that_lost_access_to_group_is_rejected(session):
    group, _ = await make_group(session)
    store_id = uuid.uuid4()
    session.add(StorePanelGroup(store_id=store_id, panel_group_id=group.id, is_enabled=False))
    await session.flush()
    with pytest.raises(AppError):
        await resolve_order_group(session, store_id=store_id, product=make_product(group))


async def test_manual_group_requires_a_member_panel(session):
    group, panels = await make_group(session, mode="manual")
    product = await sell(session, make_product(None), group)
    ok = await resolve_order_group(session, store_id=None, product=product, panel_group_id=group.id, selected_panel_id=panels["P1"].id)
    assert ok == (group.id, panels["P1"].id)
    with pytest.raises(AppError) as e:
        await resolve_order_group(session, store_id=None, product=product, panel_group_id=group.id, selected_panel_id=uuid.uuid4())
    assert e.value.code == "PANEL_NOT_IN_GROUP"


# ---------------------------------------------------------------- provisioning-time selection

@pytest.mark.parametrize(
    "server_kw, kind, fragment",
    [
        (dict(product_codes=["99"]), "purchase", "کد محصول"),
        (dict(capacity=0), "purchase", "ظرفیت"),
        (dict(allow_test=False), "test", "تست"),
        (dict(is_enabled=False), "purchase", "غیرفعال"),
    ],
)
async def test_group_routing_applies_the_same_eligibility_as_direct_routing(session, server_kw, kind, fragment):
    group, _ = await make_group(session, servers=(("S1", "P1", server_kw),))
    with pytest.raises(PanelError) as e:
        await resolve_allocation(session, order_for(group, kind=kind), make_product(group))
    assert fragment in e.value.message and "S1" in e.value.message


async def test_group_routing_skips_ineligible_server_and_uses_the_next_one(session):
    group, _ = await make_group(session, servers=(("S1", "P1", dict(product_codes=["99"])), ("S2", "P1", dict(product_codes=["10"]))))
    server, panel, g = await resolve_allocation(session, order_for(group), make_product(group))
    assert (server.name, panel.name, g.id) == ("S2", "P1", group.id)


async def test_group_with_unhealthy_panel_explains_why(session):
    group, _ = await make_group(session, panels=(("P1", "unknown"),))
    with pytest.raises(PanelError) as e:
        await resolve_allocation(session, order_for(group), make_product(group))
    assert "پنل سالم نیست" in e.value.message


async def test_provisioning_rechecks_group_state_changed_after_checkout(session):
    group, _ = await make_group(session)
    order = order_for(group)
    group.is_enabled = False
    await session.flush()
    with pytest.raises(PanelError):
        await resolve_allocation(session, order, make_product(group))


async def test_provisioning_refuses_an_order_without_a_pool(session):
    await make_group(session, servers=(("S1", "P1", {}),))
    with pytest.raises(PanelError) as e:
        await resolve_allocation(session, order_for(None), make_product(None))
    assert "بسته" in e.value.message


async def test_load_figures_cost_a_constant_number_of_queries(session):
    counter = {"n": 0}
    event.listen(session.engine_ref.sync_engine, "before_cursor_execute", lambda *a, **k: counter.__setitem__("n", counter["n"] + 1))

    async def cost(n_servers):
        group, _ = await make_group(session, servers=[(f"S{n_servers}-{i}", "P1", {}) for i in range(n_servers)])
        counter["n"] = 0
        await resolve_allocation(session, order_for(group), make_product(group))
        return counter["n"]

    small, large = await cost(2), await cost(20)
    assert small == large


# ---------------------------------------------------------------- admin rules for the default group

class _Admin:
    id = uuid.uuid4()


async def _persist(session, *objs):
    session.add_all(objs)
    await session.flush()


async def test_setting_default_group_writes_a_json_safe_audit_row(session):
    group, _ = await make_group(session)
    product = make_product(None)
    await _persist(session, product)
    out = await update_product(product.id, ProductPatch(default_panel_group_id=group.id), _Admin(), session)
    assert out.default_panel_group_id == group.id
    audit_rows = (await session.scalars(select(AuditEvent).where(AuditEvent.action == "product.updated"))).all()
    assert audit_rows and audit_rows[0].data["after"]["default_panel_group_id"] == str(group.id)


async def test_default_group_must_be_automatic_and_enabled(session):
    manual, _ = await make_group(session, mode="manual")
    off, _ = await make_group(session, enabled=False, panels=(("P2", "healthy"),), servers=(("S2", "P2", {}),))
    product = make_product(None)
    await _persist(session, product)
    for bad, code in ((manual, "DEFAULT_GROUP_MANUAL"), (off, "DEFAULT_GROUP_DISABLED")):
        with pytest.raises(AppError) as e:
            await update_product(product.id, ProductPatch(default_panel_group_id=bad.id), _Admin(), session)
        assert e.value.code == code


async def test_default_group_can_be_cleared_with_explicit_null(session):
    group, _ = await make_group(session)
    product = make_product(group)
    await _persist(session, product)
    out = await update_product(product.id, ProductPatch(default_panel_group_id=None), _Admin(), session)
    assert out.default_panel_group_id is None


async def test_create_product_accepts_and_returns_default_group(session):
    group, _ = await make_group(session)
    body = CreateProduct(code="new-1", name="plan", duration_days=30, traffic_gb=10, main_price=1, reseller_price=1, default_panel_group_id=group.id)
    out = await create_product(body, _Admin(), session)
    assert out.default_panel_group_id == group.id


async def test_group_used_as_a_default_cannot_become_manual(session):
    group, _ = await make_group(session)
    await _persist(session, make_product(group))
    with pytest.raises(AppError) as e:
        await update_panel_group(group.id, UpdatePanelGroup(selection_mode="manual"), _Admin(), session)
    assert e.value.code == "DEFAULT_GROUP_IN_USE"
