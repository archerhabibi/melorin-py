"""Reseller stores are connected to the main packages and sales bundles automatically (never overwriting decisions)."""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401
from melorin.core.db import Base
from melorin.modules.catalog import service as catalog
from melorin.kernel.models.catalog import Product, StoreProduct
from melorin.modules.reseller.linking import link_bundle_to_resellers, link_product_to_resellers, link_store_catalog
from melorin.kernel.models.stores import Store
from melorin.kernel.models.bundles import Bundle, BundleProduct, StoreBundle


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


def mk_store(kind="reseller"):
    return Store(kind=kind, name="S", slug=f"s-{uuid.uuid4().hex[:6]}", currency="IRT", status="active")


def mk_product(code, **kw):
    return Product(code=code, name=code, duration_days=30, traffic_gb=30, main_price=30000, reseller_price=20000, currency="IRT", **kw)


async def count(s, model, *where):
    return await s.scalar(sa.select(sa.func.count()).select_from(model).where(*where))


async def test_new_reseller_store_gets_all_packages_and_bundles(session):
    p1, p2, test_p, archived = await add(
        session, mk_product("A"), mk_product("B"), mk_product("T", is_test=True), mk_product("X", is_active=False)
    )
    on, off = await add(session, Bundle(name="on", reseller_enabled=True), Bundle(name="off", reseller_enabled=False))
    st = await add(session, mk_store())
    assert await link_store_catalog(session, st) == (2, 1)
    rows = (await session.scalars(sa.select(StoreProduct).where(StoreProduct.store_id == st.id))).all()
    assert {r.product_id for r in rows} == {p1.id, p2.id}
    assert all(r.is_enabled and r.is_listed and r.customer_price is None for r in rows)
    assert [r.bundle_id for r in (await session.scalars(sa.select(StoreBundle).where(StoreBundle.store_id == st.id))).all()] == [on.id]
    assert await link_store_catalog(session, st) == (0, 0)  # idempotent


async def test_main_store_is_not_linked_by_this_helper(session):
    await add(session, mk_product("A"))
    main = await add(session, mk_store("main"))
    assert await link_store_catalog(session, main) == (0, 0)


async def test_new_package_and_bundle_reach_every_existing_reseller_store(session):
    s1, s2, main = await add(session, mk_store(), mk_store(), mk_store("main"))
    p = await add(session, mk_product("N"))
    assert await link_product_to_resellers(session, p) == 2
    assert await count(session, StoreProduct, StoreProduct.product_id == p.id, StoreProduct.store_id == main.id) == 0
    b = await add(session, Bundle(name="n"))
    assert await link_bundle_to_resellers(session, b) == 2
    b_off = await add(session, Bundle(name="off", reseller_enabled=False))
    assert await link_bundle_to_resellers(session, b_off) == 0


async def test_linking_never_overwrites_an_admin_decision_or_a_reseller_price(session):
    st = await add(session, mk_store())
    p = await add(session, mk_product("A"))
    b = await add(session, Bundle(name="b"))
    await add(
        session,
        StoreProduct(store_id=st.id, product_id=p.id, is_enabled=False, is_listed=False, customer_price=45000),
        StoreBundle(store_id=st.id, bundle_id=b.id, is_enabled=False),
    )
    assert await link_store_catalog(session, st) == (0, 0)
    sp = await session.scalar(sa.select(StoreProduct).where(StoreProduct.store_id == st.id))
    assert (sp.is_enabled, sp.is_listed, sp.customer_price) == (False, False, 45000)
    assert (await session.scalar(sa.select(StoreBundle.is_enabled).where(StoreBundle.store_id == st.id))) is False


async def test_linked_store_can_be_priced_by_the_reseller(session):
    """The visible symptom: before linking, the reseller's price table was empty."""
    from melorin.modules.catalog import allocation

    st = await add(session, mk_store())
    p = await add(session, mk_product("A"))
    g = await add(session, Bundle(name="g"))
    await add(session, BundleProduct(bundle_id=g.id, product_id=p.id, is_listed=True))
    assert await catalog.enabled_for_store(session, st) == []
    await link_store_catalog(session, st)
    assert [row[0].id for row in await catalog.enabled_for_store(session, st)] == [p.id]
    assert [r["product_id"] for r in await allocation.reseller_price_table(session, st)] == [p.id]
    await allocation.set_customer_price(session, st, p.id, 35000)  # the reseller can now set a price
