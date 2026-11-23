"""DB-003: a ledger transaction is reversed at most once, whatever idempotency key the second caller uses."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from _db import make_store, make_user, open_session
from melorin.kernel.models.wallet import LedgerTransaction
from melorin.modules.wallet import service as wallet


async def _credited_wallet(s, amount: int = 1000):
    store, user = await make_store(s), await make_user(s)
    w = await wallet.get_wallet(s, user.id, store.id)
    tx, _ = await wallet.post(
        s,
        kind="topup",
        key="seed",
        currency="IRT",
        store_id=store.id,
        postings=[wallet.Posting(-amount, account=wallet.acc_store_topup(store.id, "manual_card")), wallet.Posting(amount, wallet=w)],
    )
    await s.commit()
    return w, tx


@pytest.mark.asyncio
async def test_second_reversal_under_another_key_returns_the_first_and_debits_once():
    async with open_session() as s:
        w, tx = await _credited_wallet(s)
        first = await wallet.reverse(s, tx, key="refund:a")
        second = await wallet.reverse(s, tx, key="refund:b")
        await s.commit()
        assert second.id == first.id
        await s.refresh(w)
        assert w.balance == 0  # 1000 credited and reversed once; before DB-003 the second key left -1000
        count = await s.scalar(select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.reverses_id == tx.id))
        assert count == 1


@pytest.mark.asyncio
async def test_same_key_replay_is_still_a_noop():
    async with open_session() as s:
        w, tx = await _credited_wallet(s)
        first = await wallet.reverse(s, tx, key="refund:a")
        again = await wallet.reverse(s, tx, key="refund:a")
        await s.commit()
        assert again.id == first.id
        await s.refresh(w)
        assert w.balance == 0


@pytest.mark.asyncio
async def test_database_refuses_a_second_reversal_row():
    async with open_session() as s:
        _, tx = await _credited_wallet(s)
        await wallet.reverse(s, tx, key="refund:a")
        await s.commit()
        s.add(LedgerTransaction(kind="reversal", idempotency_key="forged", currency="IRT", reverses_id=tx.id))
        with pytest.raises(IntegrityError):
            await s.flush()
        await s.rollback()
