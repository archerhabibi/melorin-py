"""M7.7: concurrency properties that SQLite cannot prove (``FOR UPDATE`` is a no-op there).

These tests only run in the PostgreSQL lane (``TEST_PG_URL`` set). They open several *independent*
sessions against one private schema, so row locks and unique constraints are really exercised.
"""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, make_user, open_schema_engine, pg_url
from melorin.core.errors import AppError
from melorin.modules.wallet import service as wallet
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction, Wallet

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="M7.7 PostgreSQL lane: set TEST_PG_URL"),
]


async def _funded_wallet(factory, balance: int):
    async with factory() as s:
        store, user = await make_store(s), await make_user(s)
        w = await wallet.get_wallet(s, user.id, store.id)
        await wallet.post(
            s,
            kind="topup",
            key="seed",
            currency="IRT",
            store_id=store.id,
            postings=[wallet.Posting(-balance, account=wallet.acc_store_topup(store.id, "manual_card")), wallet.Posting(balance, wallet=w)],
        )
        await s.commit()
        return store.id, w.id


async def _debit(factory, wallet_id, store_id, amount: int, key: str):
    async with factory() as s:
        w = await s.get(Wallet, wallet_id)
        try:
            _, created = await wallet.post(
                s,
                kind="purchase",
                key=key,
                currency="IRT",
                store_id=store_id,
                postings=[wallet.Posting(-amount, wallet=w, min_balance=0), wallet.Posting(amount, account=wallet.acc_revenue(store_id))],
            )
            await s.commit()
            return created
        except AppError:
            await s.rollback()
            return "rejected"


async def test_parallel_debits_can_never_overdraw_the_wallet():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        store_id, wallet_id = await _funded_wallet(factory, 1_000)
        results = await asyncio.gather(*[_debit(factory, wallet_id, store_id, 400, f"buy-{i}") for i in range(5)])
        assert results.count(True) == 2  # 1000 // 400 purchases fit, the rest must be refused
        assert results.count("rejected") == 3
        async with factory() as s:
            assert (await s.get(Wallet, wallet_id)).balance == 200
            assert (await s.scalar(select(func.sum(LedgerEntry.amount)))) == 0


async def test_same_idempotency_key_in_parallel_posts_exactly_once():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        store_id, wallet_id = await _funded_wallet(factory, 1_000)
        results = await asyncio.gather(*[_debit(factory, wallet_id, store_id, 100, "same-key") for _ in range(4)])
        assert results.count(True) == 1 and results.count(False) == 3
        async with factory() as s:
            assert (await s.get(Wallet, wallet_id)).balance == 900
            count = await s.scalar(
                select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.idempotency_key == "same-key")
            )
            assert count == 1
