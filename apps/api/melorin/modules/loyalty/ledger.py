"""Loyalty club: ledger (see ``service.py`` for the facade and the overview)."""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.errors import AppError
from melorin.kernel.models.loyalty import (
    LoyaltyAccount,
    LoyaltyTransaction,
)
from melorin.modules.loyalty.common import HISTORY_MAX


# ---------------------------------------------------------------- the points purse
async def get_account(session: AsyncSession, store_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False) -> LoyaltyAccount:
    """The customer's purse in this store (created on first use). ``lock`` serialises writers on the row."""
    q = select(LoyaltyAccount).where(LoyaltyAccount.store_id == store_id, LoyaltyAccount.user_id == user_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    acc = await session.scalar(q)
    if acc:
        return acc
    try:
        async with session.begin_nested():
            session.add(LoyaltyAccount(store_id=store_id, user_id=user_id, balance=0, lifetime_earned=0, debt=0))
    except IntegrityError:  # concurrent creation
        pass
    return await session.scalar(q)  # type: ignore[return-value]


async def _find_tx(session: AsyncSession, key: str) -> LoyaltyTransaction | None:
    return await session.scalar(select(LoyaltyTransaction).where(LoyaltyTransaction.idempotency_key == key))


async def _post(
    session: AsyncSession,
    acc: LoyaltyAccount,
    *,
    kind: str,
    amount: int,
    key: str,
    order_id: uuid.UUID | None = None,
    reward_id: uuid.UUID | None = None,
    reverses_id: uuid.UUID | None = None,
    memo: str | None = None,
    actor_id: uuid.UUID | None = None,
    debt_recovered: int = 0,
) -> tuple[LoyaltyTransaction, bool]:
    """Append one ledger row and move the balance. Same key => same row, nothing is posted twice. The caller locked ``acc``."""
    existing = await _find_tx(session, key)
    if existing:
        return existing, False
    after = acc.balance + amount
    if after < 0:
        raise AppError("LOYALTY_NOT_ENOUGH_POINTS", "امتیاز شما کافی نیست.", 400)
    tx = LoyaltyTransaction(
        store_id=acc.store_id,
        user_id=acc.user_id,
        account_id=acc.id,
        kind=kind,
        amount=amount,
        balance_after=after,
        order_id=order_id,
        reward_id=reward_id,
        reverses_id=reverses_id,
        idempotency_key=key,
        memo=memo,
        actor_id=actor_id,
        debt_recovered=debt_recovered,
    )
    try:
        async with session.begin_nested():
            session.add(tx)
            await session.flush()
    except IntegrityError:
        existing = await _find_tx(session, key)
        if existing:
            return existing, False
        raise
    acc.balance = after
    return tx, True


# ---------------------------------------------------------------- what customers and owners read
def tx_out(t: LoyaltyTransaction) -> dict:
    return {
        "id": t.id,
        "kind": t.kind,
        "amount": t.amount,
        "balance_after": t.balance_after,
        "order_id": t.order_id,
        "memo": t.memo,
        "created_at": t.created_at,
    }


async def history(
    session: AsyncSession, store_id: uuid.UUID, user_id: uuid.UUID, *, limit: int = 20, before: dt.datetime | None = None
) -> tuple[list[LoyaltyTransaction], bool]:
    """One page of the customer's points entries in this store, newest first. Returns (rows, has_more)."""
    limit = max(1, min(limit, HISTORY_MAX))
    q = select(LoyaltyTransaction).where(LoyaltyTransaction.store_id == store_id, LoyaltyTransaction.user_id == user_id)
    if before:
        q = q.where(LoyaltyTransaction.created_at < before)
    rows = list(
        (await session.scalars(q.order_by(LoyaltyTransaction.created_at.desc(), LoyaltyTransaction.id.desc()).limit(limit + 1))).all()
    )
    return rows[:limit], len(rows) > limit
