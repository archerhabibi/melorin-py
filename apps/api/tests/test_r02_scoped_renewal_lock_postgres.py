"""R02 (PostgreSQL lane): the scoped lock really waits for its owner's competitors and for nobody else.

Runs only with ``TEST_PG_URL`` set; SQLite ignores ``FOR UPDATE``. Three independent sessions share one private schema:

* session 1 (alice, store A) holds the lock on her account inside an open transaction, like a renewal in flight;
* session 2 (alice in store B / bob) names that same id: it must come back at once with ``None`` and must NOT wait;
* session 3 (alice, store A, a parallel tap on "renew") must really wait until session 1 ends, then see its committed state.
"""

import asyncio
import datetime as dt

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_store, make_user, open_schema_engine, pg_url
from melorin.core.scope import StoreScope
from melorin.modules.vpn.models import VpnAccount

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="R02 PostgreSQL lane: set TEST_PG_URL"),
]


async def _seed(factory):
    async with factory() as s:
        alice, bob = await make_user(s), await make_user(s)
        store_a, store_b = await make_store(s), await make_store(s, kind="reseller", owner=await make_user(s))
        product = await make_product(s)
        order = await make_order(s, user=alice, store=store_a, product=product)
        acct = VpnAccount(
            username="alice_in_a", user_id=alice.id, store_id=store_a.id, order_id=order.id, product_id=product.id, status="active",
            expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=5), traffic_limit_bytes=0, traffic_used_bytes=0, links=[],
        )
        s.add(acct)
        await s.commit()
        return alice.id, bob.id, store_a.id, store_b.id, acct.id


async def test_foreign_scopes_never_wait_but_the_owner_does():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        alice, bob, store_a, store_b, acct_id = await _seed(factory)

        async with factory() as holder:
            assert await StoreScope(store_id=store_a, user_id=alice).lock(holder, VpnAccount, acct_id) is not None  # lock is now held

            async def locked_by(user_id, store_id):
                async with factory() as s:
                    row = await StoreScope(store_id=store_id, user_id=user_id).lock(s, VpnAccount, acct_id)
                    got = row.id if row is not None else None  # read before rollback expires the instance
                    await s.rollback()
                    return got

            # another store / another customer: answered immediately, nothing to wait for
            assert await asyncio.wait_for(locked_by(alice, store_b), timeout=2) is None
            assert await asyncio.wait_for(locked_by(bob, store_a), timeout=2) is None

            # the owner's own parallel request is the one that must queue behind the first
            waiting = asyncio.create_task(locked_by(alice, store_a))
            await asyncio.sleep(0.5)
            assert not waiting.done(), "a second renewal of the same account must wait for the first"

            await holder.commit()  # first request finishes, lock released
            assert await asyncio.wait_for(waiting, timeout=5) == acct_id
