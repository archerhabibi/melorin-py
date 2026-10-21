"""Double-entry, append-only, idempotent ledger. Wallet.balance is a locked projection."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import events
from melorin.core.errors import AppError
from melorin.domain.ledger import LedgerError, Line, apply_to_balance, validate_balanced
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction, Wallet


def acc_wallet(w: Wallet) -> str:
    return f"wallet:{w.id}"


def acc_revenue(store_id) -> str:
    return f"store:{store_id}:revenue"


def acc_referral_expense(store_id) -> str:
    return f"store:{store_id}:referral_expense"


def acc_clearing(provider: str) -> str:
    return f"gateway:{provider}:clearing"


def acc_manual(store_id) -> str:
    return f"store:{store_id}:manual_adjustment"


@dataclass
class Posting:
    amount: int
    wallet: Wallet | None = None
    account: str | None = None
    min_balance: int | None = 0  # for wallet debits; None = unchecked (reversal/admin)


async def get_wallet(
    session: AsyncSession, user_id: uuid.UUID, store_id: uuid.UUID, *, currency: str = "IRT", kind: str = "customer"
) -> Wallet:
    q = select(Wallet).where(Wallet.user_id == user_id, Wallet.store_id == store_id, Wallet.kind == kind, Wallet.currency == currency)
    w = await session.scalar(q)
    if w:
        return w
    try:
        async with session.begin_nested():
            w = Wallet(user_id=user_id, store_id=store_id, currency=currency, kind=kind, balance=0)
            session.add(w)
    except IntegrityError:  # concurrent creation
        w = await session.scalar(q)
    return w


def acc_store_topup(store_id, provider: str) -> str:
    """Clearing account of a store's own payment destination (money landed at that seller)."""
    return f"store:{store_id}:topup:{provider}"


def acc_reseller_cash(store_id) -> str:
    """Cash a reseller collected directly from its customers (manual top-ups by the reseller)."""
    return f"store:{store_id}:reseller_cash"


def acc_coupon_platform(store_id) -> str:
    return f"store:{store_id}:platform_coupon_expense"


async def find_tx(session: AsyncSession, key: str) -> LedgerTransaction | None:
    return await session.scalar(select(LedgerTransaction).where(LedgerTransaction.idempotency_key == key))


async def lock_wallets(session: AsyncSession, wallets: list[Wallet]) -> None:
    ids = sorted({w.id for w in wallets}, key=str)  # stable order => no deadlocks
    if ids:
        await session.execute(
            select(Wallet).where(Wallet.id.in_(ids)).order_by(Wallet.id).with_for_update().execution_options(populate_existing=True)
        )


async def post(
    session: AsyncSession,
    *,
    kind: str,
    key: str,
    currency: str,
    postings: list[Posting],
    store_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    payment_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    memo: str | None = None,
    reverses_id: uuid.UUID | None = None,
) -> tuple[LedgerTransaction, bool]:
    """Returns (transaction, created). Same key => same transaction, no double posting."""
    existing = await find_tx(session, key)
    if existing:
        return existing, False
    wallets = [p.wallet for p in postings if p.wallet is not None]
    if any(w.currency != currency for w in wallets):
        raise AppError("CURRENCY_MISMATCH", "واحد پول ناهمخوان است.", 400)
    await lock_wallets(session, wallets)
    lines = [
        Line(acc_wallet(p.wallet) if p.wallet else p.account, p.amount, p.wallet.id if p.wallet else None, p.min_balance) for p in postings
    ]
    try:
        validate_balanced(lines)
    except LedgerError as e:
        raise AppError(e.code, e.message, 500) from e
    tx = LedgerTransaction(
        kind=kind,
        idempotency_key=key,
        store_id=store_id,
        order_id=order_id,
        payment_id=payment_id,
        actor_id=actor_id,
        currency=currency,
        memo=memo,
        reverses_id=reverses_id,
    )
    try:
        async with session.begin_nested():
            session.add(tx)
            await session.flush()
    except IntegrityError:
        existing = await find_tx(session, key)
        if existing:
            return existing, False
        raise
    for p, line in zip(postings, lines, strict=True):
        after = None
        if p.wallet is not None:
            try:
                after = apply_to_balance(p.wallet.balance, line)
            except LedgerError as e:
                raise AppError(e.code, e.message, 402) from e
            p.wallet.balance = after
            await events.emit(
                session,
                events.WALLET_CHANGED,
                {
                    "wallet_id": p.wallet.id,
                    "user_id": p.wallet.user_id,
                    "store_id": p.wallet.store_id,
                    "amount": p.amount,
                    "balance": after,
                    "kind": kind,
                },
            )
        session.add(
            LedgerEntry(transaction_id=tx.id, account=line.account, wallet_id=line.wallet_key, amount=line.amount, balance_after=after)
        )
    return tx, True


async def reverse(
    session: AsyncSession, tx: LedgerTransaction, *, key: str, kind: str = "reversal", actor_id=None, memo=None
) -> LedgerTransaction:
    """Compensating transaction: negates every entry; history is never mutated."""
    existing = await find_tx(session, key)
    if existing:
        return existing
    entries = (await session.scalars(select(LedgerEntry).where(LedgerEntry.transaction_id == tx.id))).all()
    postings = []
    for e in entries:
        w = await session.get(Wallet, e.wallet_id) if e.wallet_id else None
        postings.append(Posting(-e.amount, wallet=w, account=None if w else e.account, min_balance=None))
    new, _ = await post(
        session,
        kind=kind,
        key=key,
        currency=tx.currency,
        postings=postings,
        store_id=tx.store_id,
        order_id=tx.order_id,
        payment_id=tx.payment_id,
        actor_id=actor_id,
        memo=memo,
        reverses_id=tx.id,
    )
    return new
