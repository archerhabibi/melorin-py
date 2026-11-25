"""Reversals and account consolidation must agree on the wallet that holds the money."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, make_user, open_schema_engine, pg_url
from melorin.core.config import get_settings
from melorin.core.errors import AppError
from melorin.domain.account_linking import Evidence
from melorin.kernel.models.person import AccountConsolidationOperation
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction, Wallet
from melorin.modules.identity.account_linking import consolidation, linking
from melorin.modules.wallet import service as wallets

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="PostgreSQL row locks are required"),
]


async def test_refund_waiting_for_a_wallet_follows_a_concurrent_consolidation(monkeypatch):
    monkeypatch.setattr(get_settings(), "identity_consolidation_auto_approve", False)
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            store = await make_store(s)
            a, b = await make_user(s), await make_user(s)
            await linking.attach_identity(s, a, "google", "ga", evidence=Evidence.OAUTH_GOOGLE)
            await linking.attach_identity(s, b, "google", "gb", evidence=Evidence.OAUTH_GOOGLE)
            with pytest.raises(AppError) as conflict:
                await linking.attach_identity(s, a, "google", "gb", evidence=Evidence.OAUTH_GOOGLE)
            await linking.confirm_person_link(s, a, uuid.UUID(conflict.value.details["operation_id"]))
            await s.refresh(b)
            source = await wallets.get_wallet(s, b.id, store.id)
            await wallets.post(
                s,
                kind="topup",
                key="seed",
                currency="IRT",
                postings=[wallets.Posting(500, wallet=source), wallets.Posting(-500, account="gateway:clearing")],
            )
            purchase, _ = await wallets.post(
                s,
                kind="purchase",
                key="purchase",
                currency="IRT",
                postings=[wallets.Posting(-200, wallet=source, min_balance=0), wallets.Posting(200, account="store:revenue")],
            )
            await s.commit()
            op = await consolidation.request(s, a, key="race-consolidation")
            await s.commit()
            store_id, central_id, source_id, purchase_id, op_id = store.id, a.id, source.id, purchase.id, op.id

        async with factory() as refund_session:
            waiting, release = asyncio.Event(), asyncio.Event()
            original_lock = wallets.lock_wallets

            async def gated_lock(session, locked_wallets):
                if session is refund_session and not waiting.is_set():
                    waiting.set()
                    await release.wait()
                await original_lock(session, locked_wallets)

            monkeypatch.setattr(wallets, "lock_wallets", gated_lock)

            async def refund():
                purchase = await refund_session.get(LedgerTransaction, purchase_id)
                await wallets.reverse(refund_session, purchase, key="race-refund", kind="refund")
                await refund_session.commit()

            task = asyncio.create_task(refund())
            try:
                await asyncio.wait_for(waiting.wait(), timeout=15)
                async with factory() as s:
                    op = await s.get(AccountConsolidationOperation, op_id)
                    await asyncio.wait_for(consolidation.execute(s, op, approver_id=None, actor_type="system"), timeout=15)
                release.set()
                await asyncio.wait_for(task, timeout=15)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        async with factory() as s:
            source = await s.get(Wallet, source_id)
            central = await wallets.get_wallet(s, central_id, store_id, route=False)
            assert source.status == "consolidated" and source.balance == 0
            assert central.balance == 500
            assert (await s.scalar(select(func.sum(LedgerEntry.amount)))) == 0
