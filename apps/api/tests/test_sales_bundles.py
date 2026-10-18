"""Sales bundles (UI: بسته فروش): connection kind, per-bundle package prices, customer-facing bundle lists,
mandatory custom names and the admin rules around a bundle's packages. Runs against in-memory SQLite."""

import importlib.util
import types
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from _source import read_source
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401
from alembic.migration import MigrationContext
from alembic.operations import Operations
from melorin.core.db import Base
from melorin.core.errors import AppError
from melorin.modules.admin import router as admin
from melorin.modules.admin.schemas import BundleProductIn, CreateBundle, CreateProduct, ProductPatch, UpdateBundle
from melorin.modules.catalog import router as public
from melorin.modules.catalog import service as catalog
from melorin.modules.catalog.models import Product, StoreProduct
from melorin.modules.stores.models import Store
from melorin.modules.vpn import allocation
from melorin.modules.vpn.allocation import requested_account_name
from melorin.modules.vpn.bundles import Bundle, BundleMember, BundleProduct
from melorin.modules.vpn.models import Panel, Server

ADMIN = types.SimpleNamespace(id=uuid.uuid4())
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.sorted_tables:  # one by one: a pre-existing duplicate index breaks create_all on SQLite
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
        except Exception:
            pass
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def add(s, *objs):
    s.add_all(objs)
    await s.flush()
    return objs[0] if len(objs) == 1 else objs


async def main_store(s, kind="main"):
    return await add(s, Store(kind=kind, name="S", slug=f"s-{uuid.uuid4().hex[:6]}", currency="IRT", status="active"))


async def product(s, code, gb, price, reseller=None, **kw):
    p = await add(
        s,
        Product(
            code=code,
            name=f"{gb}G",
            duration_days=30,
            traffic_gb=gb,
            main_price=price,
            reseller_price=reseller or price // 2,
            currency="IRT",
            **kw,
        ),
    )
    return p


async def bundle(s, name="Bundle", *, kind="direct", mode="automatic", naming="automatic", healthy="healthy", **kw):
    g = await add(s, Bundle(name=name, kind_label=kind, selection_mode=mode, naming_mode=naming, **kw))
    panel = await add(s, Panel(name=f"internal-{name}", kind="mock", base_url="http://x", is_enabled=True, health_status=healthy))
    await add(s, BundleMember(bundle_id=g.id, panel_id=panel.id, sort=0), Server(name=f"srv-{name}", panel_id=panel.id))
    return g, panel


async def sell(s, group, prod, store, *, main=None, reseller=None, listed=True, sort=0, customer_price=None):
    await add(
        s, BundleProduct(bundle_id=group.id, product_id=prod.id, main_price=main, reseller_price=reseller, is_listed=listed, sort=sort)
    )
    if not await s.scalar(sa.select(StoreProduct.id).where(StoreProduct.store_id == store.id, StoreProduct.product_id == prod.id)):
        await add(s, StoreProduct(store_id=store.id, product_id=prod.id, is_enabled=True, is_listed=True, customer_price=customer_price))


# ---------------------------------------------------------------- pricing per bundle
async def test_bundle_price_overrides_only_what_it_sets(session):
    p = await product(session, "30", 30, 30000, reseller=20000)
    g, _ = await bundle(session)
    assert allocation.effective_prices(p, None) == (30000, 20000)
    pp = BundleProduct(bundle_id=g.id, product_id=p.id, main_price=45000)
    assert allocation.effective_prices(p, pp) == (45000, 20000)  # reseller cost falls back to the product's own
    pp.reseller_price = 31000
    assert allocation.effective_prices(p, pp) == (45000, 31000)


async def test_same_package_has_a_different_price_in_each_bundle(session):
    store = await main_store(session)
    p = await product(session, "30", 30, 30000)
    direct, _ = await bundle(session, "Direct")
    tunnel, _ = await bundle(session, "Tunnel", kind="tunnel")
    await sell(session, direct, p, store)
    await sell(session, tunnel, p, store, main=50000)
    assert [price for *_, price in await allocation.bundle_packages(session, store, direct.id)] == [30000]
    assert [price for *_, price in await allocation.bundle_packages(session, store, tunnel.id)] == [50000]


async def test_quote_uses_the_bundle_price_and_reseller_cost(session):
    p = await product(session, "30", 30, 30000, reseller=20000)
    g, _ = await bundle(session)
    pp = BundleProduct(bundle_id=g.id, product_id=p.id, main_price=45000, reseller_price=33000)
    main = types.SimpleNamespace(kind="main", currency="IRT")
    q = await catalog.build_quote(None, main, p, None, None, 0, prices=allocation.effective_prices(p, pp))
    assert (q.unit_price, q.total, q.reseller_cost) == (45000, 45000, None)
    reseller = types.SimpleNamespace(kind="reseller", currency="IRT")
    q = await catalog.build_quote(
        None,
        reseller,
        p,
        types.SimpleNamespace(customer_price=60000),
        None,
        0,
        main_currency="IRT",
        prices=allocation.effective_prices(p, pp),
    )
    assert (q.unit_price, q.reseller_cost) == (60000, 33000)


async def test_hidden_and_foreign_packages_are_not_listed(session):
    store = await main_store(session)
    g, _ = await bundle(session)
    shown, hidden, test_pkg = (
        await product(session, "a", 10, 1000),
        await product(session, "b", 20, 2000),
        await product(session, "t", 1, 0, is_test=True),
    )
    await sell(session, g, shown, store)
    await sell(session, g, hidden, store, listed=False)
    await add(session, BundleProduct(bundle_id=g.id, product_id=test_pkg.id))
    await add(session, StoreProduct(store_id=store.id, product_id=test_pkg.id, is_enabled=True, is_listed=True))
    assert [p.code for p, *_ in await allocation.bundle_packages(session, store, g.id)] == ["a"]


async def test_reseller_store_lists_its_own_customer_price(session):
    store = await main_store(session, "reseller")
    g, _ = await bundle(session)
    p = await product(session, "a", 10, 1000)
    await sell(session, g, p, store, customer_price=1500)
    assert [price for *_, price in await allocation.bundle_packages(session, store, g.id)] == [1500]


async def test_flat_catalog_hides_products_no_bundle_sells(session):
    store = await main_store(session)
    g, _ = await bundle(session)
    bundled, orphan = await product(session, "a", 10, 1000), await product(session, "b", 20, 2000)
    await sell(session, g, bundled, store)
    await add(session, StoreProduct(store_id=store.id, product_id=orphan.id, is_enabled=True, is_listed=True))
    assert {p.code for p, _ in await catalog.store_catalog(session, store)} == {"a", "b"}
    assert {p.code for p, _ in await allocation.sellable_products(session, store)} == {"a"}


# ---------------------------------------------------------------- what the customer sees
async def test_customer_bundle_list_skips_disabled_full_and_empty_bundles(session):
    store = await main_store(session)
    p = await product(session, "a", 10, 1000)
    ok, _ = await bundle(session, "OK", kind="tunnel")
    off, _ = await bundle(session, "Off", is_enabled=False)
    full, _ = await bundle(session, "Full", sales_limit=1, sold_count=1)
    empty, _ = await bundle(session, "Empty")
    for g in (ok, off, full):
        await sell(session, g, p, store)
    out = await public.bundles(store.id, session)
    assert [(x.name, x.kind_label, x.panels) for x in out] == [("OK", "tunnel", [])]


async def test_manual_bundle_shows_labels_never_internal_panel_names(session):
    store = await main_store(session)
    p = await product(session, "a", 10, 1000)
    g, panel = await bundle(session, "Manual", mode="manual")
    sick = await add(session, Panel(name="secret-sick-host", kind="mock", base_url="http://y", is_enabled=True, health_status="down"))
    await add(session, BundleMember(bundle_id=g.id, panel_id=sick.id, sort=1))
    member = await session.scalar(sa.select(BundleMember).where(BundleMember.panel_id == panel.id))
    member.label = "آلمان"
    await sell(session, g, p, store)
    (out,) = await public.bundles(store.id, session)
    assert [(x.id, x.label) for x in out.panels] == [(panel.id, "آلمان")]  # unhealthy panel not offered
    member.label = None
    (out,) = await public.bundles(store.id, session)
    assert out.panels[0].label == "گزینه 1" and "internal" not in out.panels[0].label


async def test_bundle_packages_endpoint_refuses_a_bundle_the_store_cannot_sell(session):
    store = await main_store(session)
    g, _ = await bundle(session, "Empty")
    with pytest.raises(AppError) as e:
        await public.bundle_packages(store.id, g.id, session)
    assert e.value.code == "NOT_FOUND"


# ---------------------------------------------------------------- naming
def test_custom_bundle_requires_a_usable_name_and_cleans_it():
    custom, auto = types.SimpleNamespace(naming_mode="custom"), types.SimpleNamespace(naming_mode="automatic")
    assert requested_account_name(custom, "  ali vpn!! ") == "alivpn"
    assert requested_account_name(custom, "a" * 80) == "a" * 40
    for bad in (None, "", "  ", "ab", "فارسی", "!!"):
        with pytest.raises(AppError) as e:
            requested_account_name(custom, bad)
        assert e.value.code == "ACCOUNT_NAME_REQUIRED"
    assert requested_account_name(auto, "anything") is None


# ---------------------------------------------------------------- admin
def test_kind_label_is_free_text_chosen_by_the_admin():
    assert CreateBundle(name="ab").kind_label == ""
    for ok in ("direct", "آلمان - پرسرعت", "هر چیزی"):
        assert CreateBundle(name="ab", kind_label=ok).kind_label == ok
    with pytest.raises(ValidationError):
        CreateBundle(name="ab", kind_label="x" * 41)
    assert UpdateBundle(kind_label="x").kind_label == "x"


async def test_admin_creates_a_bundle_with_kind_and_customer_labels(session):
    panel = await add(session, Panel(name="p", kind="mock", base_url="http://x"))
    body = CreateBundle(
        name="Tunnel bundle", kind_label="tunnel", selection_mode="manual", panel_ids=[panel.id], member_labels={panel.id: " ترکیه "}
    )
    out = await admin.create_bundle(body, ADMIN, session)
    assert out["kind_label"] == "tunnel" and out["panels"][0]["label"] == "ترکیه"
    out = await admin.update_bundle(out["id"], UpdateBundle(kind_label="softether", member_labels={panel.id: ""}), ADMIN, session)
    assert out["kind_label"] == "softether" and out["panels"][0]["label"] is None


async def test_admin_sets_lists_and_removes_bundle_packages(session):
    g, _ = await bundle(session)
    p = await product(session, "a", 10, 1000, reseller=600)
    out = await admin.set_bundle_product(g.id, p.id, BundleProductIn(main_price=1200), ADMIN, session)
    assert [x["product_ids"] for x in await admin.list_bundles(ADMIN, session)] == [[str(p.id)]]
    assert (out["main_price"], out["reseller_price"], out["base_main_price"]) == (1200, None, 1000)
    out = await admin.set_bundle_product(g.id, p.id, BundleProductIn(main_price=None, is_listed=False, sort=3), ADMIN, session)
    assert (out["main_price"], out["is_listed"], out["sort"]) == (None, False, 3)
    assert [r["code"] for r in await admin.list_bundle_products(g.id, ADMIN, session)] == ["a"]
    assert [r["code"] for r in await admin.unassigned_products(ADMIN, session)] == []
    await admin.remove_bundle_product(g.id, p.id, ADMIN, session)
    assert [r["code"] for r in await admin.unassigned_products(ADMIN, session)] == ["a"]


async def test_test_packages_cannot_be_sold_in_a_bundle_and_default_bundle_cannot_be_removed(session):
    g, _ = await bundle(session)
    t = await product(session, "t", 1, 0, is_test=True)
    with pytest.raises(AppError) as e:
        await admin.set_bundle_product(g.id, t.id, BundleProductIn(), ADMIN, session)
    assert e.value.code == "TEST_PRODUCT_NOT_SELLABLE"
    p = await product(session, "a", 10, 1000, default_bundle_id=g.id)
    await admin.set_bundle_product(g.id, p.id, BundleProductIn(), ADMIN, session)
    with pytest.raises(AppError) as e:
        await admin.remove_bundle_product(g.id, p.id, ADMIN, session)
    assert e.value.code == "PRODUCT_DEFAULT_BUNDLE"


async def test_choosing_a_default_bundle_also_makes_the_bundle_sell_the_package(session):
    g, _ = await bundle(session)
    out = await admin.create_product(
        CreateProduct(code="new", name="plan", duration_days=30, traffic_gb=10, main_price=1, reseller_price=1, default_bundle_id=g.id),
        ADMIN,
        session,
    )
    assert await session.scalar(sa.select(BundleProduct.id).where(BundleProduct.bundle_id == g.id, BundleProduct.product_id == out.id))
    p = await product(session, "b", 10, 1000)
    await admin.update_product(p.id, ProductPatch(default_bundle_id=g.id), ADMIN, session)
    assert await session.scalar(sa.select(BundleProduct.id).where(BundleProduct.bundle_id == g.id, BundleProduct.product_id == p.id))


# ---------------------------------------------------------------- migration 0016
def _load_migration():
    spec = importlib.util.spec_from_file_location("m0016", ROOT / "alembic/versions/0016_sales_pools.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_0016_follows_0015_and_fits_alembic_version_column():
    m = _load_migration()
    assert m.down_revision == "0015_ticket_upgrade" and len(m.revision) <= 32
    prev = read_source(ROOT / "alembic/versions/0015_ticket_upgrade.py")
    assert 'revision = "0015_ticket_upgrade"' in prev


def test_migration_0016_adds_columns_table_and_backfills_default_bundles():
    m = _load_migration()
    eng = sa.create_engine("sqlite://")
    gid, pid, orphan = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE panel_groups (id CHAR(32) PRIMARY KEY, name VARCHAR(120))")
        conn.exec_driver_sql("CREATE TABLE panel_group_members (id CHAR(32) PRIMARY KEY, panel_group_id CHAR(32))")
        conn.exec_driver_sql("CREATE TABLE products (id CHAR(32) PRIMARY KEY, default_panel_group_id CHAR(32))")
        conn.exec_driver_sql("INSERT INTO panel_groups VALUES (?, 'g')", (gid.hex,))
        conn.exec_driver_sql("INSERT INTO products VALUES (?, ?)", (pid.hex, gid.hex))
        conn.exec_driver_sql("INSERT INTO products VALUES (?, NULL)", (orphan.hex,))
        with Operations.context(MigrationContext.configure(conn)):
            m.upgrade()
        rows = conn.exec_driver_sql("SELECT panel_group_id, product_id, main_price, is_listed FROM pool_products").fetchall()
        assert [(r[0], r[1], r[2], bool(r[3])) for r in rows] == [(gid.hex, pid.hex, None, True)]  # the bundle-less product is left alone
        cols = {c["name"]: c for c in sa.inspect(conn).get_columns("panel_groups")}
        assert "kind_label" in cols and "label" in {c["name"] for c in sa.inspect(conn).get_columns("panel_group_members")}
        with Operations.context(MigrationContext.configure(conn)):
            m.downgrade()
        assert "pool_products" not in sa.inspect(conn).get_table_names()


async def test_plan_sale_is_the_single_core_answer_for_route_name_and_price(session):
    p = await product(session, "30", 30, 30000, reseller=20000)
    g, _ = await bundle(session)
    session.add(BundleProduct(bundle_id=g.id, product_id=p.id, main_price=45000))
    await session.flush()
    store = types.SimpleNamespace(id=None, kind="main", currency="IRT")
    plan = await allocation.plan_sale(session, store=store, product=p, sp=None, bundle_id=g.id)
    assert (plan.group_id, plan.unit_price, plan.prices) == (g.id, 45000, (45000, 20000))
    with pytest.raises(AppError) as e:
        await allocation.plan_sale(session, store=store, product=p, sp=None)
    assert e.value.code == "BUNDLE_REQUIRED"
    other = Bundle(name="other", selection_mode="automatic", naming_mode="automatic")
    session.add(other)
    await session.flush()
    with pytest.raises(AppError) as e:
        await allocation.plan_sale(session, store=store, product=p, sp=None, bundle_id=other.id)
    assert e.value.code == "PRODUCT_NOT_IN_BUNDLE"


def test_channels_and_modules_outside_the_core_hold_no_route_or_price_rule():
    for rel in ("melorin/modules/orders/service.py", "melorin/modules/catalog/router.py", "melorin/modules/catalog/service.py"):
        src = (ROOT / rel).read_text()
        for banned in ("BundleProduct", "BundleMember", "effective_prices", "unit_price_of"):
            assert banned not in src, f"{rel} must leave {banned} to vpn/allocation.py"


async def test_customer_price_can_never_be_below_the_bundles_reseller_price(session):
    """reseller_price differs per bundle; customer_price is one per product and must cover the bundle being sold."""
    reseller = await main_store(session, "reseller")
    p = await product(session, "30", 30, 30000, reseller=20000)
    cheap, _ = await bundle(session, "Cheap")
    dear, _ = await bundle(session, "Dear")
    await sell(session, cheap, p, reseller, reseller=20000, customer_price=25000)
    await add(session, BundleProduct(bundle_id=dear.id, product_id=p.id, reseller_price=40000))
    sp = await session.scalar(sa.select(StoreProduct).where(StoreProduct.store_id == reseller.id))
    # listing: only the bundle whose cost the customer price covers
    assert [pp.bundle_id for _, _, pp, _ in await allocation.bundle_packages(session, reseller, cheap.id)] == [cheap.id]
    assert await allocation.bundle_packages(session, reseller, dear.id) == []
    assert {v.group.id for v in await allocation.sellable_bundles(session, reseller)} == {cheap.id}
    # checkout: same rule, refused by the core
    plan = await allocation.plan_sale(session, store=reseller, product=p, sp=sp, bundle_id=cheap.id)
    assert plan.unit_price == 25000 and plan.reseller_price == 20000
    with pytest.raises(AppError) as e:
        await allocation.plan_sale(session, store=reseller, product=p, sp=sp, bundle_id=dear.id)
    assert e.value.code == "CUSTOMER_PRICE_BELOW_COST"
    # setting: the floor is the highest bundle cost
    assert await allocation.reseller_price_floor(session, p) == 40000
    with pytest.raises(AppError):
        await allocation.ensure_customer_price(session, p, 39999)
    await allocation.ensure_customer_price(session, p, 40000)
    await allocation.ensure_customer_price(session, p, None)
    assert await allocation.stores_below_cost(session, p, 26000) == 1
    # flat catalog follows the same rule, a product in no bundle is never shown
    assert [x.code for x, _ in await allocation.sellable_products(session, reseller)] == ["30"]
    sp.customer_price = 15000
    await session.flush()
    assert await allocation.sellable_products(session, reseller) == []
    loose = await product(session, "loose", 10, 1000)
    await add(session, StoreProduct(store_id=reseller.id, product_id=loose.id, is_enabled=True, is_listed=True, customer_price=5000))
    assert await allocation.sellable_products(session, reseller) == []


async def test_each_reseller_store_sets_its_own_customer_price_in_the_core(session):
    a, b = await main_store(session, "reseller"), await main_store(session, "reseller")
    p = await product(session, "30", 30, 30000, reseller=20000)
    g, _ = await bundle(session, "G")
    await sell(session, g, p, a, reseller=20000)
    await add(session, StoreProduct(store_id=b.id, product_id=p.id, is_enabled=True, is_listed=True))
    # nothing priced yet: both stores see the product in their price table, neither sells it
    for st in (a, b):
        rows = await allocation.reseller_price_table(session, st)
        assert [(r["code"], r["state"], r["cost_floor"]) for r in rows] == [("30", "unset", 20000)]
        assert await allocation.sellable_products(session, st) == []
    # each reseller prices independently; the floor is that of the bundles selling the product
    await allocation.set_customer_price(session, a, p.id, 26000)
    await allocation.set_customer_price(session, b, p.id, 31000)
    with pytest.raises(AppError) as e:
        await allocation.set_customer_price(session, a, p.id, 19999)
    assert e.value.code == "CUSTOMER_PRICE_BELOW_COST"
    sa_, sb_ = [await session.scalar(sa.select(StoreProduct).where(StoreProduct.store_id == s.id)) for s in (a, b)]
    assert (sa_.customer_price, sb_.customer_price) == (26000, 31000)
    pa = await allocation.plan_sale(session, store=a, product=p, sp=sa_, bundle_id=g.id)
    pb = await allocation.plan_sale(session, store=b, product=p, sp=sb_, bundle_id=g.id)
    assert (pa.unit_price, pb.unit_price) == (26000, 31000) and pa.reseller_price == pb.reseller_price == 20000
    # clearing hides the product again; the main store cannot price, and unknown products are refused
    await allocation.set_customer_price(session, a, p.id, None)
    assert await allocation.sellable_products(session, a) == []
    main = await main_store(session)
    with pytest.raises(AppError):
        await allocation.set_customer_price(session, main, p.id, 30000)
    with pytest.raises(Exception):
        await allocation.set_customer_price(session, a, uuid.uuid4(), 30000)


async def test_admin_availability_never_writes_a_resellers_customer_price(session):
    reseller = await main_store(session, "reseller")
    p = await product(session, "30", 30, 30000, reseller=20000)
    g, _ = await bundle(session, "G")
    await sell(session, g, p, reseller, reseller=20000, customer_price=26000)
    from melorin.modules.admin.schemas import Availability

    await admin.set_availability(p.id, Availability(store_id=reseller.id, enabled=True, listed=False, customer_price=99), ADMIN, session)
    sp = await session.scalar(sa.select(StoreProduct).where(StoreProduct.store_id == reseller.id))
    assert sp.customer_price == 26000 and sp.is_listed is False
