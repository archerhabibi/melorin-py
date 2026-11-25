"""Property-based ledger invariants: any mix of credits, debits (some overdrafts) and replayed keys keeps the books true.

PostgreSQL lane only (``TEST_PG_URL``): SQLite/pysqlite does not honour rollback of released savepoints, so the
"failed debit leaves no orphan transaction" property can only be proven on the real database.
"""

import asyncio

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from sqlalchemy import func, select

from _db import make_store, make_user, open_session, pg_url
from melorin.core.errors import AppError
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction
from melorin.modules.wallet import service as wallet

pytestmark = pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL")

OPS = st.lists(
    st.tuples(st.sampled_from(["credit", "debit"]), st.integers(min_value=1, max_value=10_000), st.integers(min_value=0, max_value=6)),
    min_size=1,
    max_size=25,
)


def _tx(kind, w, store, amount, key):
    if kind == "credit":
        postings = [wallet.Posting(-amount, account=wallet.acc_store_topup(store.id, "manual_card")), wallet.Posting(amount, wallet=w)]
    else:
        postings = [wallet.Posting(-amount, wallet=w, min_balance=0), wallet.Posting(amount, account=wallet.acc_revenue(store.id))]
    return dict(kind="topup" if kind == "credit" else "purchase", key=key, currency="IRT", store_id=store.id, postings=postings)


async def _run(ops):
    async with open_session() as s:
        store, user = await make_store(s), await make_user(s)
        w = await wallet.get_wallet(s, user.id, store.id)
        await s.commit()
        w_id = w.id
        model, applied = 0, {}
        for kind, amount, key_n in ops:
            key = f"k{key_n}"
            try:
                _, created = await wallet.post(s, **_tx(kind, w, store, amount, key))
                await s.commit()
            except AppError:
                await s.rollback()  # what a request does on a failed debit
                await s.refresh(w)
                await s.refresh(store)
                assert kind == "debit" and key not in applied
                assert model < amount  # refused only when it really would overdraw
                continue
            if key in applied:
                assert not created  # replayed key never posts twice
            else:
                assert created
                applied[key] = (kind, amount)
                model += amount if kind == "credit" else -amount
            await s.refresh(w)
            assert w.balance == model >= 0
        assert await s.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0))) == 0  # whole ledger nets to zero
        assert await s.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.wallet_id == w_id)) == w.balance
        assert (await s.scalar(select(func.count()).select_from(LedgerTransaction))) == len(applied)  # no orphan transactions


@settings(max_examples=25, deadline=None, suppress_health_check=list(HealthCheck))
@given(OPS)
def test_ledger_stays_balanced_idempotent_and_non_negative(ops):
    asyncio.run(_run(ops))
