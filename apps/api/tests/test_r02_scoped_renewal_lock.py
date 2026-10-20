"""R02: the row lock a renewal takes on the account is taken THROUGH the buyer's StoreScope.

Before: ``create_order`` did ``session.get(VpnAccount, id, with_for_update=True)`` and only afterwards checked who owns the
row, so naming somebody else's account id (another customer, or the same customer's account in another store) locked that
row for a moment and could stall its real owner. Now the scope conditions are part of the ``SELECT ... FOR UPDATE`` itself:
a foreign id is simply "not found" and nothing is locked.

SQLite cannot show lock waits (``FOR UPDATE`` is a no-op there), so this file proves the SQL shape and the behaviour; the
PostgreSQL lane proves the waiting itself in ``test_r02_scoped_renewal_lock_postgres.py``."""

import datetime as dt
import inspect
import types

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core.deps import StoreContext
from melorin.core.errors import AppError
from melorin.core.scope import StoreScope
from melorin.modules.orders import service as orders
from melorin.modules.orders.models import Order
from melorin.modules.stores.models import StoreMembership
from melorin.modules.vpn.models import VpnAccount

NOW = dt.datetime.now(dt.UTC)


async def _account(s, *, user, store, product, name):
    order = await make_order(s, user=user, store=store, product=product)
    a = VpnAccount(
        username=name, user_id=user.id, store_id=store.id, order_id=order.id, product_id=product.id, status="active",
        expires_at=NOW + dt.timedelta(days=5), traffic_limit_bytes=10 * 1024**3, traffic_used_bytes=0, subscription_url=f"https://sub.test/{name}", links=[],
    )
    s.add(a)
    await s.flush()
    return a


async def _world(s):
    """alice shops in stores A and B with one login; bob only in A. Each owns one account per store he shops in."""
    alice, bob = await make_user(s), await make_user(s)
    store_a, store_b = await make_store(s), await make_store(s, kind="reseller", owner=await make_user(s))
    product = await make_product(s)
    membership = StoreMembership(store_id=store_a.id, user_id=alice.id, role="customer", status="active")
    s.add(membership)
    a_in_a = await _account(s, user=alice, store=store_a, product=product, name="alice_in_a")
    a_in_b = await _account(s, user=alice, store=store_b, product=product, name="alice_in_b")
    b_in_a = await _account(s, user=bob, store=store_a, product=product, name="bob_in_a")
    await s.commit()
    return types.SimpleNamespace(**locals())


# ------------------------------------------------------------------ the statement
async def test_the_lock_statement_has_for_update_and_both_scope_conditions():
    """What PostgreSQL will really receive: one SELECT ... FOR UPDATE whose WHERE already contains user AND store."""
    seen = []

    class Spy:
        async def scalar(self, stmt):
            seen.append(stmt)

    scope = StoreScope(store_id=__import__("uuid").uuid4(), user_id=__import__("uuid").uuid4())
    await scope.lock(Spy(), VpnAccount, __import__("uuid").uuid4())
    assert len(seen) == 1
    sql = str(seen[0].compile(dialect=postgresql.dialect()))
    assert sql.rstrip().endswith("FOR UPDATE")
    where = sql.split("WHERE", 1)[1]
    assert "vpn_accounts.id =" in where and "vpn_accounts.user_id =" in where and "vpn_accounts.store_id =" in where
    assert seen[0].get_execution_options().get("populate_existing") is True


# ------------------------------------------------------------------ behaviour
async def test_lock_returns_only_rows_of_this_user_in_this_store():
    async with open_session() as s:
        w = await _world(s)
        in_a = StoreScope(store_id=w.store_a.id, user_id=w.alice.id)
        assert (await in_a.lock(s, VpnAccount, w.a_in_a.id)).username == "alice_in_a"
        assert await in_a.lock(s, VpnAccount, w.a_in_b.id) is None  # same login, other store
        assert await in_a.lock(s, VpnAccount, w.b_in_a.id) is None  # other customer, same store
        assert await StoreScope(store_id=w.store_b.id, user_id=w.alice.id).lock(s, VpnAccount, w.a_in_b.id) is not None


async def test_lock_refreshes_an_instance_that_is_already_in_the_session():
    """After the lock the checks must see what a concurrent request committed, not the copy loaded earlier."""
    async with open_session() as s:
        w = await _world(s)
        cached = await s.get(VpnAccount, w.a_in_a.id)
        await s.execute(VpnAccount.__table__.update().where(VpnAccount.id == w.a_in_a.id).values(status="revoked"))
        locked = await StoreScope(store_id=w.store_a.id, user_id=w.alice.id).lock(s, VpnAccount, w.a_in_a.id)
        assert locked is cached and locked.status == "revoked"


async def test_renewing_a_foreign_account_is_refused_before_any_order_or_money_exists():
    async with open_session() as s:
        w = await _world(s)
        ctx = StoreContext(store=w.store_a, user=w.alice, membership=w.membership)
        before = await s.scalar(select(func.count()).select_from(Order))
        for i, foreign in enumerate((w.a_in_b, w.b_in_a)):
            with pytest.raises(AppError, match="ACCOUNT_NOT_RENEWABLE") as e:
                await orders.create_order(
                    s, ctx, product_id=w.product.id, idempotency_key=f"k{i}", kind="renewal", vpn_account_id=foreign.id, channel="web"
                )
            assert e.value.status == 409
        assert await s.scalar(select(func.count()).select_from(Order)) == before  # no order, no debit, nothing to roll back


async def test_a_missing_account_id_answers_exactly_like_a_foreign_one():
    """Ids cannot be probed: unknown, foreign-store and foreign-customer ids all give the same code and message."""
    import uuid

    async with open_session() as s:
        w = await _world(s)
        ctx = StoreContext(store=w.store_a, user=w.alice, membership=w.membership)
        answers = set()
        for n, acct_id in enumerate((uuid.uuid4(), w.a_in_b.id, w.b_in_a.id)):
            with pytest.raises(AppError) as e:
                await orders.create_order(s, ctx, product_id=w.product.id, idempotency_key=f"p{n}", kind="renewal", vpn_account_id=acct_id, channel="web")
            answers.add((e.value.code, e.value.status, e.value.message))
        assert len(answers) == 1


# ------------------------------------------------------------------ guard
def test_create_order_never_locks_an_account_by_bare_id_again():
    src = inspect.getsource(orders.create_order)
    assert "get(VpnAccount" not in src, "lock the account through StoreScope.lock, not session.get(..., with_for_update=True)"
    assert "StoreScope(store_id=store_id, user_id=user_id).lock(session, VpnAccount" in src
