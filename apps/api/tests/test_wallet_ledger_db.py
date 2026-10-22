"""M7.1: wallet ledger against real tables - credit/debit, idempotency, overdraft, currency and reversal."""

import pytest
from sqlalchemy import func, select

from _db import make_store, make_user, open_session
from melorin.core.errors import AppError
from melorin.modules.wallet import service as wallet
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction


async def _setup(s):
    store = await make_store(s)
    user = await make_user(s)
    w = await wallet.get_wallet(s, user.id, store.id)
    return store, user, w


def _credit(w, store, amount, key):
    return dict(
        kind="topup",
        key=key,
        currency="IRT",
        store_id=store.id,
        postings=[wallet.Posting(-amount, account=wallet.acc_store_topup(store.id, "manual_card")), wallet.Posting(amount, wallet=w)],
    )


def _debit(w, store, amount, key):
    return dict(
        kind="purchase",
        key=key,
        currency="IRT",
        store_id=store.id,
        postings=[wallet.Posting(-amount, wallet=w, min_balance=0), wallet.Posting(amount, account=wallet.acc_revenue(store.id))],
    )


async def test_credit_then_debit_updates_balance_and_writes_balanced_entries():
    async with open_session() as s:
        store, _, w = await _setup(s)
        tx, created = await wallet.post(s, **_credit(w, store, 5_000, "k1"))
        assert created and w.balance == 5_000
        await wallet.post(s, **_debit(w, store, 2_000, "k2"))
        await s.commit()
        assert w.balance == 3_000
        total = await s.scalar(select(func.sum(LedgerEntry.amount)))
        assert total == 0  # double entry: the whole ledger always nets to zero
        assert (await s.scalar(select(func.count()).select_from(LedgerTransaction))) == 2
        last = (await s.scalars(select(LedgerEntry).where(LedgerEntry.wallet_id == w.id).order_by(LedgerEntry.created_at))).all()
        assert sorted(e.balance_after for e in last) == [3_000, 5_000]


async def test_same_idempotency_key_never_posts_twice():
    async with open_session() as s:
        store, _, w = await _setup(s)
        first, created1 = await wallet.post(s, **_credit(w, store, 700, "dup"))
        second, created2 = await wallet.post(s, **_credit(w, store, 700, "dup"))
        assert created1 and not created2
        assert first.id == second.id
        assert w.balance == 700


async def test_debit_beyond_balance_is_rejected_with_402_and_leaves_balance_untouched():
    async with open_session() as s:
        store, _, w = await _setup(s)
        await wallet.post(s, **_credit(w, store, 100, "c"))
        with pytest.raises(AppError) as exc:
            await wallet.post(s, **_debit(w, store, 101, "d"))
        assert exc.value.code == "INSUFFICIENT_FUNDS" and exc.value.status == 402
        assert w.balance == 100


async def test_currency_mismatch_is_rejected_before_any_posting():
    async with open_session() as s:
        store, _, w = await _setup(s)
        bad = _credit(w, store, 10, "c")
        bad["currency"] = "USD"
        with pytest.raises(AppError) as exc:
            await wallet.post(s, **bad)
        assert exc.value.code == "CURRENCY_MISMATCH"
        assert w.balance == 0
        assert (await s.scalar(select(func.count()).select_from(LedgerTransaction))) == 0


async def test_unbalanced_posting_is_a_server_error_and_posts_nothing():
    async with open_session() as s:
        store, _, w = await _setup(s)
        with pytest.raises(AppError) as exc:
            await wallet.post(
                s,
                kind="topup",
                key="x",
                currency="IRT",
                postings=[wallet.Posting(10, wallet=w), wallet.Posting(-9, account="gateway:x:clearing")],
            )
        assert exc.value.code == "LEDGER_UNBALANCED" and exc.value.status == 500
        assert w.balance == 0


async def test_reverse_negates_every_entry_once_and_is_idempotent():
    async with open_session() as s:
        store, _, w = await _setup(s)
        tx, _ = await wallet.post(s, **_credit(w, store, 900, "orig"))
        rev = await wallet.reverse(s, tx, key="orig:rev", kind="topup_refund")
        again = await wallet.reverse(s, tx, key="orig:rev", kind="topup_refund")
        assert rev.id == again.id and rev.reverses_id == tx.id
        assert w.balance == 0
        assert (await s.scalar(select(func.sum(LedgerEntry.amount)))) == 0


async def test_reversal_may_overdraw_wallet_by_policy():
    async with open_session() as s:
        store, _, w = await _setup(s)
        tx, _ = await wallet.post(s, **_credit(w, store, 1_000, "orig"))
        await wallet.post(s, **_debit(w, store, 900, "spend"))
        await wallet.reverse(s, tx, key="orig:rev")
        assert w.balance == -900  # spent money cannot be clawed back; the debt is recorded, not hidden


async def test_get_wallet_is_get_or_create_per_user_store_kind_and_currency():
    async with open_session() as s:
        store, user, w = await _setup(s)
        again = await wallet.get_wallet(s, user.id, store.id)
        other_kind = await wallet.get_wallet(s, user.id, store.id, kind="reseller_credit")
        other_cur = await wallet.get_wallet(s, user.id, store.id, currency="USD")
        assert again.id == w.id
        assert len({w.id, other_kind.id, other_cur.id}) == 3


async def test_wallet_changed_event_is_queued_for_each_wallet_posting():
    from melorin.kernel.models.system import OutboxEvent

    async with open_session() as s:
        store, _, w = await _setup(s)
        await wallet.post(s, **_credit(w, store, 50, "c"))
        await s.flush()
        topics = (await s.scalars(select(OutboxEvent.topic))).all()
        assert topics.count("wallet.changed") == 1
