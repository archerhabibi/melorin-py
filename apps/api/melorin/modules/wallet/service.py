"""Double-entry, append-only, idempotent ledger. Wallet.balance is a locked projection."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import events
from melorin.core.errors import AppError
from melorin.domain.ledger import LedgerError, Line, apply_to_balance, validate_balanced
from melorin.kernel.models.identity import User
from melorin.kernel.models.person import Person
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction, Wallet


def acc_wallet(w: Wallet) -> str:
    return f"wallet:{w.id}"


def acc_revenue(store_id) -> str:
    return f"store:{store_id}:revenue"


def acc_referral_expense(store_id) -> str:
    return f"store:{store_id}:referral_expense"


def acc_loyalty_expense(store_id) -> str:
    """What a store's loyalty club pays out: wallet credit given for points comes from here."""
    return f"store:{store_id}:loyalty_expense"


@dataclass
class Posting:
    amount: int
    wallet: Wallet | None = None
    account: str | None = None
    min_balance: int | None = 0  # for wallet debits; None = unchecked (reversal/admin)


def _posting_account(p: Posting) -> str:
    """Ledger account of one posting: its wallet's account, else the explicit one (a posting needs one of the two)."""
    if p.wallet:
        return acc_wallet(p.wallet)
    if p.account is None:
        raise ValueError("a ledger posting needs a wallet or an account")
    return p.account


async def get_wallet(
    session: AsyncSession, user_id: uuid.UUID, store_id: uuid.UUID, *, currency: str = "IRT", kind: str = "customer", route: bool = True
) -> Wallet:
    """The wallet an account spends from. After a person consolidation (docs/25) every account of that person is routed to the
    central account's wallet; ``route=False`` returns the account's own row (used by the consolidation itself)."""
    q = select(Wallet).where(Wallet.user_id == user_id, Wallet.store_id == store_id, Wallet.kind == kind, Wallet.currency == currency)
    w = await session.scalar(q)
    if route and kind == "customer":
        routed = await _central_wallet(session, user_id, store_id, currency, w)
        if routed is not None:
            return routed
    if w:
        return w
    try:
        async with session.begin_nested():
            w = Wallet(user_id=user_id, store_id=store_id, currency=currency, kind=kind, balance=0)
            session.add(w)
    except IntegrityError:  # concurrent creation
        w = await session.scalar(q)
    return w


async def _central_wallet(
    session: AsyncSession, user_id: uuid.UUID, store_id: uuid.UUID, currency: str, own: Wallet | None
) -> Wallet | None:
    """The central wallet to use instead of ``own``, or None. Funds that are still in an account's own active wallet stay usable
    there until a consolidation moves them (money is never hidden by a routing rule)."""
    hops = 0
    while own is not None and own.status == "consolidated" and own.consolidated_into_id and hops < 4:
        own = await session.get(Wallet, own.consolidated_into_id)
        hops += 1
        if own is not None and own.status != "consolidated":
            return own
    user = await session.get(User, user_id)
    person = await session.get(Person, user.person_id) if user is not None and user.person_id else None
    if person is None or person.central_user_id is None or person.central_user_id == user_id:
        return None
    if own is not None and own.balance != 0:
        return None
    return await get_wallet(session, person.central_user_id, store_id, currency=currency, route=False)


def acc_store_topup(store_id, provider: str) -> str:
    """Clearing account of a store's own payment destination (money landed at that seller)."""
    return f"store:{store_id}:topup:{provider}"


def acc_reseller_cash(store_id) -> str:
    """Cash a reseller collected directly from its customers (manual top-ups by the reseller)."""
    return f"store:{store_id}:reseller_cash"


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
    lines = [Line(_posting_account(p), p.amount, p.wallet.id if p.wallet else None, p.min_balance) for p in postings]
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
