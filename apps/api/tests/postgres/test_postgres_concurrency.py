"""M7.7: concurrency properties that SQLite cannot prove (``FOR UPDATE`` is a no-op there).

These tests only run in the PostgreSQL lane (``TEST_PG_URL`` set). They open several *independent*
sessions against one private schema, so row locks and unique constraints are really exercised.
"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, make_user, open_schema_engine, pg_url
from melorin.core import settings_store
from melorin.core.errors import AppError
from melorin.kernel.models.identity import User
from melorin.kernel.models.stores import Store, StoreMembership
from melorin.modules.wallet import service as wallet
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction, Wallet
from melorin.modules.reseller.routes.customers import adjust_customer_wallet_core
from melorin.modules.reseller.schemas import CustomerWalletAdjustment

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


async def test_parallel_reversals_of_one_transaction_under_different_keys_reverse_it_once():
    """DB-003: two refund paths racing on the same original transaction must not both debit the books."""
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        store_id, wallet_id = await _funded_wallet(factory, 1_000)
        async with factory() as s:
            seed_id = (await wallet.find_tx(s, "seed")).id

        async def reverse_once(key: str):
            async with factory() as s:
                done = await wallet.reverse(s, await s.get(LedgerTransaction, seed_id), key=key)
                await s.commit()
                return done.id

        ids = await asyncio.gather(*[reverse_once(f"refund-{i}") for i in range(4)])
        assert len(set(ids)) == 1
        async with factory() as s:
            assert (await s.get(Wallet, wallet_id)).balance == 0
            count = await s.scalar(select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.reverses_id == seed_id))
            assert count == 1
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


@pytest.mark.parametrize("same_key", [True, False])
async def test_parallel_reseller_corrections_replay_once_without_overdrawing(same_key):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        store_id, wallet_id = await _funded_wallet(factory, 1_000)
        async with factory() as s:
            customer_id = (await s.get(Wallet, wallet_id)).user_id
            s.add(StoreMembership(store_id=store_id, user_id=customer_id, role="customer", status="active"))
            await s.commit()

        async def correct(key):
            async with factory() as s:
                ctx = SimpleNamespace(store=await s.get(Store, store_id), user=await s.get(User, customer_id))
                body = CustomerWalletAdjustment(amount=-1000, reason="correction", idempotency_key=key)
                try:
                    return await adjust_customer_wallet_core(s, ctx, customer_id, body)
                except AppError as exc:
                    await s.rollback()
                    return exc.code

        keys = ["same-correction"] * 4 if same_key else [f"correction-{i}" for i in range(4)]
        results = await asyncio.gather(*(correct(key) for key in keys))
        successes = [result for result in results if isinstance(result, dict)]
        assert len(successes) == (4 if same_key else 1)
        assert len({result["transaction_id"] for result in successes}) == 1
        assert all(result == "INSUFFICIENT_FUNDS" for result in results if isinstance(result, str))
        async with factory() as s:
            assert (await s.get(Wallet, wallet_id)).balance == 0
            assert (await s.scalar(select(func.sum(LedgerEntry.amount)))) == 0


async def test_reseller_retry_waits_for_the_original_after_cap_is_lowered(monkeypatch):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        store_id, wallet_id = await _funded_wallet(factory, 1_000)
        async with factory() as s:
            customer_id = (await s.get(Wallet, wallet_id)).user_id
            s.add(StoreMembership(store_id=store_id, user_id=customer_id, role="customer", status="active"))
            await settings_store.set_value(s, "reseller.manual_topup_max", 1000)
            await s.commit()

        async with factory() as first_session, factory() as retry_session:
            first_ctx = SimpleNamespace(store=await first_session.get(Store, store_id), user=await first_session.get(User, customer_id))
            retry_ctx = SimpleNamespace(store=await retry_session.get(Store, store_id), user=await retry_session.get(User, customer_id))
            body = CustomerWalletAdjustment(amount=-1000, reason="correction", idempotency_key="cap-race-001")
            first_ready, retry_waiting, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            original_commit, original_lock = first_session.commit, wallet.lock_wallets

            async def gated_commit():
                first_ready.set()
                await release.wait()
                await original_commit()

            async def observed_lock(session, wallets):
                if session is retry_session:
                    retry_waiting.set()
                await original_lock(session, wallets)

            monkeypatch.setattr(first_session, "commit", gated_commit)
            monkeypatch.setattr(wallet, "lock_wallets", observed_lock)
            first = asyncio.create_task(adjust_customer_wallet_core(first_session, first_ctx, customer_id, body))
            retry = waiter = None
            try:
                await asyncio.wait_for(first_ready.wait(), timeout=15)
                async with factory() as s:
                    await settings_store.set_value(s, "reseller.manual_topup_max", 400)
                    await s.commit()
                retry = asyncio.create_task(adjust_customer_wallet_core(retry_session, retry_ctx, customer_id, body))
                waiter = asyncio.create_task(retry_waiting.wait())
                done, _ = await asyncio.wait({retry, waiter}, timeout=15, return_when=asyncio.FIRST_COMPLETED)
                if retry in done:
                    await retry
                    pytest.fail("retry finished before waiting for the original transaction")
                assert waiter in done, "retry never reached the wallet lock"
                release.set()
                first_result, retry_result = await asyncio.wait_for(asyncio.gather(first, retry), timeout=15)
                assert first_result["transaction_id"] == retry_result["transaction_id"]
                assert first_result["balance"] == retry_result["balance"] == 0
            finally:
                release.set()
                tasks = [task for task in (first, retry, waiter) if task is not None]
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        async with factory() as s:
            assert (await s.get(Wallet, wallet_id)).balance == 0
            assert (await s.scalar(select(func.sum(LedgerEntry.amount)))) == 0
            count = await s.scalar(
                select(func.count())
                .select_from(LedgerTransaction)
                .where(LedgerTransaction.idempotency_key == f"reseller-adjust:{store_id}:cap-race-001")
            )
            assert count == 1
