"""Per-package switch for resellers: main off => resellers off; reseller off => only resellers lose it."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401
from melorin.core.db import Base
from melorin.modules.catalog import service as catalog
from melorin.modules.catalog.models import Product, StoreProduct
from melorin.modules.stores.models import Store
from melorin.modules.vpn import allocation
from melorin.modules.vpn.bundles import Bundle, BundleProduct


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


async def setup(s):
    main = Store(kind="main", name="M", slug=f"m-{uuid.uuid4().hex[:6]}", currency="IRT", status="active")
    res = Store(kind="reseller", name="R", slug=f"r-{uuid.uuid4().hex[:6]}", currency="IRT", status="active")
    p = Product(code="P", name="P", duration_days=30, traffic_gb=30, main_price=30000, reseller_price=20000, currency="IRT")
    b = Bundle(name="B")
    s.add_all([main, res, p, b])
    await s.flush()
    s.add_all(
        [
            StoreProduct(store_id=main.id, product_id=p.id, customer_price=None),
            StoreProduct(store_id=res.id, product_id=p.id, customer_price=25000),
            BundleProduct(bundle_id=b.id, product_id=p.id),
        ]
    )
    await s.flush()
    return main, res, p, b


async def test_defaults_are_on_for_everyone(session):
    main, res, p, b = await setup(session)
    assert p.reseller_enabled is True
    assert [x.id for x, _ in await catalog.store_catalog(session, main)] == [p.id]
    assert [x.id for x, _ in await catalog.store_catalog(session, res)] == [p.id]
    assert [r[0].id for r in await allocation.bundle_packages(session, res, b.id)] == [p.id]


async def test_reseller_switch_hides_only_from_resellers(session):
    main, res, p, b = await setup(session)
    p.reseller_enabled = False
    await session.flush()
    assert [x.id for x, _ in await catalog.store_catalog(session, main)] == [p.id]
    assert await catalog.store_catalog(session, res) == []
    assert await catalog.enabled_for_store(session, res) == []
    assert await allocation.bundle_packages(session, res, b.id) == []
    assert len(await allocation.bundle_packages(session, main, b.id)) == 1
    with pytest.raises(Exception):
        await catalog.get_sellable(session, res, p.id)


async def test_main_off_hides_from_resellers_too(session):
    main, res, p, b = await setup(session)
    p.is_active = False
    await session.flush()
    assert await catalog.store_catalog(session, main) == []
    assert await catalog.store_catalog(session, res) == []
    assert await allocation.bundle_packages(session, res, b.id) == []


async def test_single_bundle_is_used_when_there_is_no_default(session):
    main, res, p, b = await setup(session)
    gid, _ = await allocation.resolve_order_group(session, store_id=main.id, product=p)
    assert gid == b.id
    b2 = Bundle(name="B2")
    session.add(b2)
    await session.flush()
    session.add(BundleProduct(bundle_id=b2.id, product_id=p.id))
    await session.flush()
    with pytest.raises(Exception):
        await allocation.resolve_order_group(session, store_id=main.id, product=p)
