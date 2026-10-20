"""R03: the free test-account quota belongs to a customer IN ONE STORE, like his wallet, orders and accounts.

Before, ``create_test_order`` counted every grant of the user across the whole platform: someone who took a test in
reseller bot A could not take one in bot B, which contradicts "every store is separate". Now the count, the cooldown and the
serialising row lock are all taken through ``StoreScope`` (this user, this store). The grant row already carried ``store_id``,
so there is no migration and old grants simply count in the store where they were given.

SQLite lane: rules and statements. The PostgreSQL lane (``test_r03_test_account_per_store_postgres.py``) proves the lock."""

import datetime as dt
import inspect
import itertools
import types

import pytest
from sqlalchemy import select

from _db import make_product, make_store, make_user, open_session
from melorin.core import codes, settings_store
from melorin.core.deps import StoreContext
from melorin.core.errors import AppError
from melorin.modules.orders import service as orders
from melorin.modules.orders.models import Order
from melorin.modules.stores.models import StoreMembership
from melorin.modules.system import models as system_models
from melorin.modules.vpn import allocation


@pytest.fixture(autouse=True)
def _sqlite_helpers(monkeypatch):
    counter = itertools.count(1)

    async def next_code(session, sequence):
        return f"T{next(counter):05d}"

    async def no_group(session, *, store_id, product, **kw):  # bundle placement has its own tests; here only the quota matters
        return None, None

    monkeypatch.setattr(codes, "next_code", next_code)
    monkeypatch.setattr(allocation, "resolve_order_group", no_group)


async def _member(s, user, store, *, status="active"):
    m = StoreMembership(store_id=store.id, user_id=user.id, role="customer", status=status)
    s.add(m)
    await s.flush()
    return m


async def _world(s):
    """alice uses store A and store B with one login; bob only A. A test package exists."""
    alice, bob = await make_user(s), await make_user(s)
    store_a, store_b = await make_store(s), await make_store(s, kind="reseller", owner=await make_user(s))
    test_product = await make_product(s)
    test_product.code, test_product.is_test = "TEST", True
    m = {(u.id, st.id): await _member(s, u, st) for u, st in ((alice, store_a), (alice, store_b), (bob, store_a))}
    await s.commit()
    for u in (alice, bob):
        await s.refresh(u, ["identities"])  # the service reads user.identities; async code cannot lazy-load it
    ctx = lambda u, st: StoreContext(store=st, user=u, membership=m[(u.id, st.id)])  # noqa: E731
    return types.SimpleNamespace(**locals())


async def _grants(s, user, store=None):
    q = select(system_models.TestAccountGrant).where(system_models.TestAccountGrant.user_id == user.id)
    if store is not None:
        q = q.where(system_models.TestAccountGrant.store_id == store.id)
    return (await s.scalars(q)).all()


# ------------------------------------------------------------------ the rule
async def test_a_test_account_taken_in_one_store_does_not_use_up_the_quota_of_another_store():
    async with open_session() as s:
        w = await _world(s)
        first = await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")
        second = await orders.create_test_order(s, w.ctx(w.alice, w.store_b), "web")  # same login, other store: allowed
        assert (first.store_id, second.store_id) == (w.store_a.id, w.store_b.id)
        assert len(await _grants(s, w.alice, w.store_a)) == 1 and len(await _grants(s, w.alice, w.store_b)) == 1


async def test_the_limit_still_applies_inside_the_same_store():
    async with open_session() as s:
        w = await _world(s)
        await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")
        with pytest.raises(AppError) as e:
            await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")
        assert e.value.code == "TEST_LIMIT" and e.value.status == 409 and "این فروشگاه" in e.value.message
        assert len(await _grants(s, w.alice, w.store_a)) == 1
        assert len((await s.scalars(select(Order).where(Order.kind == "test", Order.store_id == w.store_a.id))).all()) == 1


async def test_the_cooldown_is_per_store_too():
    async with open_session() as s:
        w = await _world(s)
        await settings_store.set_value(s, "test.max_per_user", 3)
        await settings_store.set_value(s, "test.cooldown_hours", 24)
        await s.commit()
        await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")
        with pytest.raises(AppError) as e:
            await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")
        assert e.value.code == "TEST_COOLDOWN"
        await orders.create_test_order(s, w.ctx(w.alice, w.store_b), "web")  # B has its own clock


async def test_the_cooldown_passes_for_grants_older_than_the_window():
    async with open_session() as s:
        w = await _world(s)
        await settings_store.set_value(s, "test.max_per_user", 3)
        await settings_store.set_value(s, "test.cooldown_hours", 24)
        await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")
        g = (await _grants(s, w.alice, w.store_a))[0]
        g.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=25)
        await s.commit()
        await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")
        assert len(await _grants(s, w.alice, w.store_a)) == 2


async def test_other_customers_grants_never_count_against_me():
    async with open_session() as s:
        w = await _world(s)
        await orders.create_test_order(s, w.ctx(w.bob, w.store_a), "web")
        await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")  # same store, other customer


async def test_a_grant_given_before_this_change_counts_only_in_the_store_it_was_given():
    """Old rows already carry store_id, so no data migration: the quota simply follows them."""
    async with open_session() as s:
        w = await _world(s)
        old = await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")
        assert (await _grants(s, w.alice))[0].store_id == w.store_a.id == old.store_id
        with pytest.raises(AppError, match="TEST_LIMIT"):
            await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")
        await orders.create_test_order(s, w.ctx(w.alice, w.store_b), "web")


# ------------------------------------------------------------------ membership under the lock
async def test_a_blocked_or_missing_membership_cannot_take_a_test_account():
    async with open_session() as s:
        w = await _world(s)
        # blocked after the context was resolved: the lock re-reads the row, so the new status wins
        w.m[(w.alice.id, w.store_a.id)].status = "blocked"
        await s.commit()
        with pytest.raises(AppError, match="NOT_A_MEMBER"):
            await orders.create_test_order(s, w.ctx(w.alice, w.store_a), "web")
        with pytest.raises(AppError, match="NOT_A_MEMBER"):
            await orders.create_test_order(s, StoreContext(store=w.store_a, user=w.alice, membership=None), "web")
        assert await _grants(s, w.alice, w.store_a) == []


async def test_a_membership_of_another_store_cannot_be_used_as_the_lock():
    """The lock goes through the scope: a membership id that is not (this user, this store) is treated as missing."""
    async with open_session() as s:
        w = await _world(s)
        wrong = StoreContext(store=w.store_a, user=w.alice, membership=w.m[(w.alice.id, w.store_b.id)])
        with pytest.raises(AppError, match="NOT_A_MEMBER"):
            await orders.create_test_order(s, wrong, "web")


# ------------------------------------------------------------------ guard
def test_create_test_order_counts_and_locks_only_through_the_scope():
    src = inspect.getsource(orders.create_test_order)
    assert "scope.where(TestAccountGrant)" in src and "scope.lock(session, StoreMembership" in src
    assert "TestAccountGrant.user_id ==" not in src, "the quota must never be counted by user alone again"
    assert "select(User.id)" not in src, "no platform-wide per-user lock: serialise per (user, store) membership"
