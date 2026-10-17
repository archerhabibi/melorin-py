"""A reseller prices every package per sales bundle (UI: بسته فروش) in their own store.

Two levels, one rule: the pool's own price wins, else the store-wide price of the package; a price below the
reseller price (cost) of THAT pool is refused when set, hidden from every list and refused again at checkout.
Runs against in-memory SQLite.
"""

import importlib.util
import types
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401
from melorin.core.db import Base
from melorin.core.errors import AppError
from melorin.modules.admin import router as admin
from melorin.modules.catalog import service as catalog
from melorin.modules.catalog.models import Product, StorePoolPrice, StoreProduct
from melorin.modules.reseller import router as reseller_router
from melorin.modules.reseller.schemas import PriceBatchIn, PriceBatchItem, PriceIn
from melorin.modules.stores.models import Store
from melorin.modules.system.models import AuditEvent
from melorin.modules.vpn import allocation
from melorin.modules.vpn.models import Panel, Server
from melorin.modules.vpn.panel_groups import PanelGroup, PanelGroupMember, PoolProduct

ADMIN = types.SimpleNamespace(id=uuid.uuid4())


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.sorted_tables:
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


async def store(s, kind="reseller"):
    return await add(s, Store(kind=kind, name="S", slug=f"s-{uuid.uuid4().hex[:6]}", currency="IRT", status="active"))


async def product(s, code, price=30000, reseller=20000, **kw):
    return await add(s, Product(code=code, name=code, duration_days=30, traffic_gb=30, main_price=price, reseller_price=reseller, currency="IRT", **kw))


async def pool(s, name, **kw):
    g = await add(s, PanelGroup(name=name, kind_label=name.lower(), **kw))
    panel = await add(s, Panel(name=f"internal-{name}", kind="mock", base_url="http://x", is_enabled=True, health_status="healthy"))
    await add(s, PanelGroupMember(panel_group_id=g.id, panel_id=panel.id, sort=0), Server(name=f"srv-{name}", panel_id=panel.id))
    return g


async def sell(s, group, prod, st, *, cost=None, customer_price=None):
    """Put ``prod`` in ``group`` (optionally with its own reseller price = cost) and enable it for the store."""
    await add(s, PoolProduct(panel_group_id=group.id, product_id=prod.id, reseller_price=cost, is_listed=True))
    if not await s.scalar(sa.select(StoreProduct.id).where(StoreProduct.store_id == st.id, StoreProduct.product_id == prod.id)):
        await add(s, StoreProduct(store_id=st.id, product_id=prod.id, is_enabled=True, is_listed=True, customer_price=customer_price))


async def sp_of(s, st, prod):
    return await s.scalar(sa.select(StoreProduct).where(StoreProduct.store_id == st.id, StoreProduct.product_id == prod.id))


async def world(s):
    """One reseller store, one package sold in a cheap (cost 20k) and a dear (cost 40k) pool."""
    st = await store(s)
    p = await product(s, "30")
    cheap, dear = await pool(s, "Cheap"), await pool(s, "Dear")
    await sell(s, cheap, p, st, cost=20000)
    await sell(s, dear, p, st, cost=40000)
    return st, p, cheap, dear


# ---------------------------------------------------------------- resolution
async def test_pool_price_wins_over_the_store_wide_price_and_falls_back_to_it(session):
    st, p, cheap, dear = await world(session)
    await allocation.set_customer_price(session, st, p.id, 45000)  # store-wide, covers both pools
    await allocation.set_pool_price(session, st, cheap.id, p.id, 27000)
    sp = await sp_of(session, st, p)
    assert [price for *_, price in await allocation.pool_packages(session, st, cheap.id)] == [27000]  # own price
    assert [price for *_, price in await allocation.pool_packages(session, st, dear.id)] == [45000]  # store-wide
    assert (await allocation.plan_sale(session, store=st, product=p, sp=sp, panel_group_id=cheap.id)).unit_price == 27000
    assert (await allocation.plan_sale(session, store=st, product=p, sp=sp, panel_group_id=dear.id)).unit_price == 45000
    # clearing the pool price returns that pool to the store-wide price and removes the row
    assert await allocation.set_pool_price(session, st, cheap.id, p.id, None) is None
    assert [price for *_, price in await allocation.pool_packages(session, st, cheap.id)] == [45000]
    assert await session.scalar(sa.select(sa.func.count()).select_from(StorePoolPrice)) == 0


async def test_a_package_priced_only_per_pool_is_sold_only_in_those_pools(session):
    st, p, cheap, dear = await world(session)
    assert await allocation.sellable_products(session, st) == []  # nothing priced yet
    await allocation.set_pool_price(session, st, cheap.id, p.id, 26000)
    assert [x.code for x, _ in await catalog.store_catalog(session, st)] == ["30"]
    assert [(x.code, price) for x, _sp, price in await allocation.sellable_products_priced(session, st)] == [("30", 26000)]
    assert {v.group.id for v in await allocation.sellable_pools(session, st)} == {cheap.id}  # dear has no price: not offered
    assert await allocation.pool_packages(session, st, dear.id) == []
    sp = await sp_of(session, st, p)
    plan = await allocation.plan_sale(session, store=st, product=p, sp=sp, panel_group_id=dear.id)
    assert plan.unit_price == 0  # no price in this pool ...
    with pytest.raises(AppError) as e:  # ... so the quote (and with it checkout) refuses, before any money moves
        await catalog.build_quote(session, st, p, sp, None, 0, main_currency="IRT", prices=plan.prices, customer_price=plan.unit_price)
    assert e.value.code == "PRICE_NOT_SET" and e.value.status == 409


async def test_flat_catalog_shows_the_lowest_valid_pool_price(session):
    st, p, cheap, dear = await world(session)
    await allocation.set_pool_price(session, st, cheap.id, p.id, 30000)
    await allocation.set_pool_price(session, st, dear.id, p.id, 55000)
    assert [price for *_, price in await allocation.sellable_products_priced(session, st)] == [30000]
    await allocation.set_pool_price(session, st, cheap.id, p.id, None)
    assert [price for *_, price in await allocation.sellable_products_priced(session, st)] == [55000]


# ---------------------------------------------------------------- the cost floor is per pool
async def test_pool_price_floor_is_that_pools_own_cost(session):
    st, p, cheap, dear = await world(session)
    await allocation.set_pool_price(session, st, cheap.id, p.id, 20000)  # exactly the cost is fine
    with pytest.raises(AppError) as e:
        await allocation.set_pool_price(session, st, cheap.id, p.id, 19999)
    assert e.value.code == "CUSTOMER_PRICE_BELOW_COST" and e.value.status == 422
    with pytest.raises(AppError):
        await allocation.set_pool_price(session, st, dear.id, p.id, 39999)  # 30k would do in "cheap", not in "dear"
    await allocation.set_pool_price(session, st, dear.id, p.id, 40000)
    # the store-wide price keeps its stricter rule: it must cover every pool selling the package
    with pytest.raises(AppError):
        await allocation.set_customer_price(session, st, p.id, 39999)


async def test_a_pool_price_that_became_too_low_is_hidden_and_refused_at_checkout(session):
    st, p, cheap, dear = await world(session)
    await allocation.set_pool_price(session, st, dear.id, p.id, 41000)
    sp = await sp_of(session, st, p)
    pp = await session.scalar(sa.select(PoolProduct).where(PoolProduct.panel_group_id == dear.id))
    assert await allocation.stores_below_cost(session, p, 45000, dear.id) == 1  # admin is warned, per pool
    assert await allocation.stores_below_cost(session, p, 41000, dear.id) == 0
    pp.reseller_price = 45000  # the admin raised the pool's cost afterwards
    await session.flush()
    assert await allocation.pool_packages(session, st, dear.id) == []
    assert await allocation.sellable_products(session, st) == []
    with pytest.raises(AppError) as e:
        await allocation.plan_sale(session, store=st, product=p, sp=sp, panel_group_id=dear.id)
    assert e.value.code == "CUSTOMER_PRICE_BELOW_COST"


# ---------------------------------------------------------------- quote
async def test_quote_charges_the_pool_price_and_the_pools_cost(session):
    st, p, cheap, dear = await world(session)
    await allocation.set_pool_price(session, st, dear.id, p.id, 52000)
    sp = await sp_of(session, st, p)
    plan = await allocation.plan_sale(session, store=st, product=p, sp=sp, panel_group_id=dear.id)
    q = await catalog.build_quote(session, st, p, sp, None, 0, main_currency="IRT", prices=plan.prices, customer_price=plan.unit_price)
    assert (q.unit_price, q.total, q.reseller_cost) == (52000, 52000, 40000)
    # old callers that pass only the StoreProduct still get its store-wide price
    sp.customer_price = 60000
    q = await catalog.build_quote(session, st, p, sp, None, 0, main_currency="IRT", prices=plan.prices)
    assert q.unit_price == 60000


# ---------------------------------------------------------------- price table (what the panel renders)
async def test_price_table_lists_every_pool_with_cost_price_source_and_state(session):
    st, p, cheap, dear = await world(session)
    off = await pool(session, "Off", is_enabled=False)
    await sell(session, off, p, st, cost=10000)
    hidden = await pool(session, "NoResellers", reseller_enabled=False)
    await sell(session, hidden, p, st, cost=10000)
    await allocation.set_customer_price(session, st, p.id, 45000)
    await allocation.set_pool_price(session, st, cheap.id, p.id, 25000)
    (row,) = await allocation.reseller_price_table(session, st)
    assert (row["customer_price"], row["cost_floor"], row["state"]) == (45000, 40000, "ok")
    assert len(row["costs"]) == 4  # the legacy per-pool cost list still names every pool
    pools = {x["pool_name"]: x for x in row["pools"]}
    assert set(pools) == {"Cheap", "Dear"}  # disabled / not-for-resellers pools are not worth pricing
    assert (pools["Cheap"]["cost"], pools["Cheap"]["price"], pools["Cheap"]["effective_price"], pools["Cheap"]["source"], pools["Cheap"]["state"]) == (20000, 25000, 25000, "pool", "ok")
    assert (pools["Dear"]["cost"], pools["Dear"]["price"], pools["Dear"]["effective_price"], pools["Dear"]["source"], pools["Dear"]["state"]) == (40000, None, 45000, "store", "ok")
    assert pools["Dear"]["open_for_store"] is True


async def test_price_table_marks_unset_and_below_cost_pools(session):
    st, p, cheap, dear = await world(session)
    (row,) = await allocation.reseller_price_table(session, st)
    assert {x["pool_name"]: (x["state"], x["effective_price"], x["source"]) for x in row["pools"]} == {"Cheap": ("unset", None, None), "Dear": ("unset", None, None)}
    sp = await sp_of(session, st, p)
    sp.customer_price = 30000  # loose store-wide price (e.g. set before the admin raised a cost)
    await session.flush()
    (row,) = await allocation.reseller_price_table(session, st)
    assert {x["pool_name"]: x["state"] for x in row["pools"]} == {"Cheap": "ok", "Dear": "below_cost"}


# ---------------------------------------------------------------- isolation and guards
async def test_each_store_has_its_own_pool_prices(session):
    a, b = await store(session), await store(session)
    p = await product(session, "30")
    g = await pool(session, "G")
    await sell(session, g, p, a, cost=20000)
    await add(session, StoreProduct(store_id=b.id, product_id=p.id, is_enabled=True, is_listed=True))
    await allocation.set_pool_price(session, a, g.id, p.id, 26000)
    await allocation.set_pool_price(session, b, g.id, p.id, 33000)
    assert [price for *_, price in await allocation.pool_packages(session, a, g.id)] == [26000]
    assert [price for *_, price in await allocation.pool_packages(session, b, g.id)] == [33000]
    await allocation.set_pool_price(session, a, g.id, p.id, None)  # clearing one store never touches the other
    assert [price for *_, price in await allocation.pool_packages(session, b, g.id)] == [33000]


async def test_pool_price_guards(session):
    st, p, cheap, dear = await world(session)
    main = await store(session, "main")
    with pytest.raises(AppError) as e:
        await allocation.set_pool_price(session, main, cheap.id, p.id, 30000)
    assert e.value.code == "NOT_A_RESELLER_STORE" and e.value.status == 403
    other_pool = await pool(session, "Other")  # does not sell the package
    with pytest.raises(AppError) as e:
        await allocation.set_pool_price(session, st, other_pool.id, p.id, 30000)
    assert e.value.code == "PRODUCT_NOT_IN_POOL"
    off = await pool(session, "Off", is_enabled=False)
    await sell(session, off, p, st, cost=10000)
    with pytest.raises(AppError) as e:
        await allocation.set_pool_price(session, st, off.id, p.id, 30000)
    assert e.value.status == 404
    with pytest.raises(AppError):
        await allocation.set_pool_price(session, st, cheap.id, uuid.uuid4(), 30000)  # unknown product
    disabled = await product(session, "dis")
    await sell(session, cheap, disabled, st, cost=1000)
    (await sp_of(session, st, disabled)).is_enabled = False  # the main store switched it off for this store
    await session.flush()
    with pytest.raises(AppError):
        await allocation.set_pool_price(session, st, cheap.id, disabled.id, 5000)


# ---------------------------------------------------------------- batch (the panel's "save all")
async def test_batch_saves_store_wide_and_pool_prices_together_and_reports_what_changed(session):
    st, p, cheap, dear = await world(session)
    changed = await allocation.set_prices_batch(session, st, [(None, p.id, 50000), (cheap.id, p.id, 27000), (dear.id, p.id, 45000)])
    assert sorted(c[2] for c in changed) == [27000, 45000, 50000]
    assert (await sp_of(session, st, p)).customer_price == 50000
    assert await allocation.store_pool_prices(session, st.id) == {(cheap.id, p.id): 27000, (dear.id, p.id): 45000}
    # sending the same values again changes nothing; sending a smaller number for one item is a change
    assert await allocation.set_prices_batch(session, st, [(None, p.id, 50000), (cheap.id, p.id, 27000)]) == []
    assert await allocation.set_prices_batch(session, st, [(cheap.id, p.id, None)]) == [(cheap.id, p.id, None)]


async def test_batch_is_all_or_nothing_and_lists_every_refused_item(session):
    st, p, cheap, dear = await world(session)
    with pytest.raises(AppError) as e:
        await allocation.set_prices_batch(session, st, [(cheap.id, p.id, 27000), (dear.id, p.id, 30000), (cheap.id, p.id, 28000), (dear.id, uuid.uuid4(), 9)])
    err = e.value
    assert err.code == "PRICES_INVALID" and err.status == 422
    assert sorted(x["code"] for x in err.details["errors"]) == ["CUSTOMER_PRICE_BELOW_COST", "DUPLICATE_ITEM", "NOT_FOUND"]
    assert all(isinstance(x["product_id"], str) for x in err.details["errors"])  # JSON-safe
    await session.rollback()  # what the request does when it raises: nothing is committed
    assert await allocation.store_pool_prices(session, st.id) == {}


# ---------------------------------------------------------------- HTTP handlers
def ctx_of(st):
    return types.SimpleNamespace(store=st, user=ADMIN)


async def test_endpoints_set_batch_and_audit_prices(session):
    st, p, cheap, dear = await world(session)
    ctx = ctx_of(st)
    out = await reseller_router.set_reseller_pool_price(cheap.id, p.id, PriceIn(customer_price=28000), ctx, session)
    assert out == {"ok": True, "pool_id": cheap.id, "product_id": p.id, "customer_price": 28000}
    body = PriceBatchIn(items=[PriceBatchItem(pool_id=dear.id, product_id=p.id, customer_price=44000), PriceBatchItem(pool_id=None, product_id=p.id, customer_price=60000)])
    res = await reseller_router.set_reseller_prices_batch(body, ctx, session)
    assert res["ok"] and res["changed"] == 2
    (row,) = res["prices"]
    assert row["customer_price"] == 60000 and {x["pool_name"]: x["price"] for x in row["pools"]} == {"Cheap": 28000, "Dear": 44000}
    events = (await session.scalars(sa.select(AuditEvent).where(AuditEvent.action.in_(("reseller.pool_price_set", "reseller.price_set"))))).all()
    assert sorted(e.action for e in events) == ["reseller.pool_price_set", "reseller.pool_price_set", "reseller.price_set"]


def test_batch_schema_bounds():
    with pytest.raises(Exception):
        PriceBatchIn(items=[])
    with pytest.raises(Exception):
        PriceBatchItem(product_id=uuid.uuid4(), customer_price=-1)
    assert PriceBatchItem(product_id=uuid.uuid4()).pool_id is None


# ---------------------------------------------------------------- admin cleanup
async def test_removing_a_package_from_a_pool_drops_the_resellers_price_for_it(session):
    st, p, cheap, dear = await world(session)
    await allocation.set_pool_price(session, st, dear.id, p.id, 50000)
    await allocation.set_pool_price(session, st, cheap.id, p.id, 25000)
    await admin.remove_pool_product(dear.id, p.id, ADMIN, session)
    assert await allocation.store_pool_prices(session, st.id) == {(cheap.id, p.id): 25000}


# ---------------------------------------------------------------- migration 0020
ROOT = Path(__file__).resolve().parents[1]


def _migration():
    spec = importlib.util.spec_from_file_location("m0020", ROOT / "alembic/versions/0020_store_pool_prices.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_0020_follows_0019_and_matches_the_model():
    m = _migration()
    assert m.down_revision == "0019_telegram_web_login" and len(m.revision) <= 32
    assert 'revision = "0019_telegram_web_login"' in (ROOT / "alembic/versions/0019_telegram_web_login.py").read_text()
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            m.upgrade()
        insp = sa.inspect(conn)
        cols = {c["name"]: c for c in insp.get_columns("store_pool_prices")}
        assert set(cols) == set(StorePoolPrice.__table__.columns.keys())
        assert not cols["customer_price"]["nullable"]
        assert {i["name"] for i in insp.get_indexes("store_pool_prices")} == {i.name for i in StorePoolPrice.__table__.indexes}
        assert any(set(u["column_names"]) == {"store_id", "panel_group_id", "product_id"} for u in insp.get_unique_constraints("store_pool_prices"))
        with Operations.context(MigrationContext.configure(conn)):
            m.downgrade()
        assert "store_pool_prices" not in sa.inspect(conn).get_table_names()
