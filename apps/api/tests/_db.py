"""Shared in-memory database helpers for money-path tests (M7.1).

SQLite is the default so the unit lane stays hermetic. Row locks (``FOR UPDATE``) are no-ops there, so
*concurrency* properties are covered by the PostgreSQL lane (M7.7); everything else (idempotency
keys, balances, state transitions, ledger balance) is exercised against real tables.

M7.7: when ``TEST_PG_URL`` is set (e.g. ``postgresql+asyncpg://melorin:test@localhost:5432/melorin``) the very
same tests run against PostgreSQL. Each test gets its own throw-away schema, so tests stay isolated and
dialect-specific bugs (time zones, locking, constraints) surface in CI.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401  (registers every table)
from melorin.core.db import Base
from melorin.modules.catalog.models import Product
from melorin.modules.identity.models import User
from melorin.modules.orders.models import Order
from melorin.modules.stores.models import Store


def pg_url() -> str | None:
    """PostgreSQL URL of the M7.7 lane, or ``None`` for the default SQLite lane."""
    url = os.environ.get("TEST_PG_URL", "").strip()
    return url or None


async def _create_tables(engine) -> None:
    # Tables are created one by one so one broken table cannot hide the rest (kept as a safety net).
    for table in Base.metadata.sorted_tables:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync_conn, t=table: t.create(sync_conn, checkfirst=True))
        except Exception:
            pass


@asynccontextmanager
async def open_schema_engine():
    """Yield an engine bound to a fresh database (SQLite memory, or a private PostgreSQL schema)."""
    url = pg_url()
    if url is None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await _create_tables(engine)
        try:
            yield engine
        finally:
            await engine.dispose()
        return
    schema = f"t_{uuid.uuid4().hex[:12]}"
    admin = create_async_engine(url)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}}, pool_size=5)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@asynccontextmanager
async def open_session():
    async with open_schema_engine() as engine, async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session


async def make_store(s, *, kind="main", currency="IRT", owner=None, slug=None) -> Store:
    store = Store(
        kind=kind,
        name=f"{kind} store",
        slug=slug or f"{kind}-{uuid.uuid4().hex[:8]}",
        currency=currency,
        owner_user_id=owner.id if owner else None,
    )
    s.add(store)
    await s.flush()
    return store


async def make_user(s, *, super_admin=False) -> User:
    user = User(display_name="u", is_super_admin=super_admin)
    s.add(user)
    await s.flush()
    return user


async def make_product(s, *, price=1000) -> Product:
    product = Product(code=uuid.uuid4().hex[:6], name="plan", duration_days=30, traffic_gb=10, main_price=price, reseller_price=price)
    s.add(product)
    await s.flush()
    return product


async def make_order(s, *, user, store, product, total=1000, status="paid", reseller_cost=None, number=None) -> Order:
    order = Order(
        number=number or uuid.uuid4().hex[:6],
        user_id=user.id,
        store_id=store.id,
        product_id=product.id,
        status=status,
        payment_method="wallet",
        currency=store.currency,
        unit_price=total,
        total=total,
        reseller_cost=reseller_cost,
        pricing_snapshot={},
        product_snapshot={},
    )
    s.add(order)
    await s.flush()
    return order
