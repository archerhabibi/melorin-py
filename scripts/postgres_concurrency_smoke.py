"""H009 integration smoke: run with real PostgreSQL and project dependencies.

This is intentionally opt-in because it creates isolated test rows in the
configured database. It exercises two concurrent ledger posts with the same
idempotency key and verifies one transaction.
"""
import asyncio
import os
import uuid

from sqlalchemy import func, select

from melorin.core.db import configure, session_factory
from melorin.modules.wallet.models import LedgerTransaction, Wallet
from melorin.modules.wallet import service as wallet


async def main():
    if not os.getenv("MELORIN_DATABASE_URL", "").startswith("postgresql"):
        raise SystemExit("MELORIN_DATABASE_URL must point to PostgreSQL")
    configure(os.environ["MELORIN_DATABASE_URL"])
    user_id, store_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory()() as session:
        w = Wallet(user_id=user_id, store_id=store_id, currency="IRT", balance=1000)
        session.add(w)
        await session.commit()
        wallet_id = w.id

    async def post_once():
        async with session_factory()() as session:
            w = await session.get(Wallet, wallet_id)
            tx, created = await wallet.post(
                session, kind="h009-smoke", key="h009-" + str(wallet_id),
                currency="IRT", store_id=store_id,
                postings=[wallet.Posting(-100, wallet=w, min_balance=0), wallet.Posting(100, account="h009:cash")],
            )
            await session.commit()
            return created

    results = await asyncio.gather(post_once(), post_once())
    async with session_factory()() as session:
        count = await session.scalar(select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.idempotency_key == "h009-" + str(wallet_id)))
        assert count == 1, count
    assert sum(results) == 1, results
    print("H009 PostgreSQL concurrency smoke passed")


if __name__ == "__main__":
    asyncio.run(main())
