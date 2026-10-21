"""R03 (PostgreSQL lane): parallel "give me a test account" requests.

Only runs with ``TEST_PG_URL`` (SQLite ignores ``FOR UPDATE``). Independent sessions on one private schema:

* the same customer tapping the button several times at once IN ONE STORE gets exactly one test account;
* the same customer in two different stores, at the same moment, gets one in each (no cross-store waiting or refusal).
"""

import asyncio
import itertools

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_product, make_store, make_user, open_schema_engine, pg_url
from melorin.core import codes
from melorin.core.deps import StoreContext
from melorin.core.errors import AppError
from melorin.kernel.models.identity import User
from melorin.modules.orders import service as orders
from melorin.kernel.models.orders import Order
from melorin.kernel.models.stores import Store, StoreMembership
from melorin.kernel.models import system as system_models
from melorin.modules.vpn import allocation

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="R03 PostgreSQL lane: set TEST_PG_URL"),
]


@pytest.fixture(autouse=True)
def _helpers(monkeypatch):
    counter = itertools.count(1)

    async def next_code(session, sequence):
        return f"P{next(counter):05d}"

    async def no_group(session, *, store_id, product, **kw):
        return None, None

    monkeypatch.setattr(codes, "next_code", next_code)
    monkeypatch.setattr(allocation, "resolve_order_group", no_group)


async def _seed(factory):
    async with factory() as s:
        alice = await make_user(s)
        store_a, store_b = await make_store(s), await make_store(s, kind="reseller", owner=await make_user(s))
        p = await make_product(s)
        p.code, p.is_test = "TEST", True
        s.add_all([StoreMembership(store_id=st.id, user_id=alice.id, role="customer", status="active") for st in (store_a, store_b)])
        await s.commit()
        return alice.id, store_a.id, store_b.id


async def _take(factory, user_id, store_id):
    """One independent request: its own session, context resolved like the real dependency does."""
    async with factory() as s:
        user = await s.scalar(select(User).where(User.id == user_id))
        store = await s.get(Store, store_id)
        m = await s.scalar(select(StoreMembership).where(StoreMembership.user_id == user_id, StoreMembership.store_id == store_id))
        try:
            await orders.create_test_order(s, StoreContext(store=store, user=user, membership=m), "web")
            return "granted"
        except AppError as e:
            await s.rollback()
            return e.code


async def _count(factory, user_id, store_id):
    async with factory() as s:
        return await s.scalar(
            select(func.count())
            .select_from(system_models.TestAccountGrant)
            .where(system_models.TestAccountGrant.user_id == user_id, system_models.TestAccountGrant.store_id == store_id)
        )


async def test_parallel_taps_in_one_store_give_exactly_one_test_account():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        alice, store_a, _ = await _seed(factory)
        results = await asyncio.gather(*[_take(factory, alice, store_a) for _ in range(6)])
        assert results.count("granted") == 1 and results.count("TEST_LIMIT") == 5
        assert await _count(factory, alice, store_a) == 1
        async with factory() as s:
            assert await s.scalar(select(func.count()).select_from(Order).where(Order.kind == "test")) == 1


async def test_the_same_moment_in_two_stores_gives_one_in_each():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        alice, store_a, store_b = await _seed(factory)
        results = await asyncio.gather(*[_take(factory, alice, st) for st in (store_a, store_b, store_a, store_b)])
        assert results.count("granted") == 2 and results.count("TEST_LIMIT") == 2
        assert await _count(factory, alice, store_a) == 1 and await _count(factory, alice, store_b) == 1
