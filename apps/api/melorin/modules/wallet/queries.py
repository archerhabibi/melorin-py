"""Ledger page behind ``GET /wallet/transactions`` (audit T11: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction


async def ledger_page(
    session: AsyncSession, wallet_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[int, list[tuple[LedgerEntry, LedgerTransaction]]]:
    """(total entries, newest-first page of (entry, transaction)) for one wallet."""
    q = (
        select(LedgerEntry, LedgerTransaction)
        .join(LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id)
        .where(LedgerEntry.wallet_id == wallet_id)
    )
    total = await session.scalar(select(func.count()).select_from(LedgerEntry).where(LedgerEntry.wallet_id == wallet_id))
    rows = (await session.execute(q.order_by(LedgerEntry.created_at.desc()).limit(limit).offset(offset))).all()
    return total or 0, [(e, t) for e, t in rows]
