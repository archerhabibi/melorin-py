"""A stale receipt upload must not undo an already completed payment decision."""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, make_user, open_schema_engine, pg_url
from melorin.core.errors import AppError
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.system import FileObject
from melorin.kernel.models.wallet import Wallet
from melorin.modules.payments import service as payments

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL"),
]


async def _payment_and_receipts(factory, initial_status):
    async with factory() as session:
        store, user = await make_store(session), await make_user(session)
        files = [
            FileObject(
                owner_user_id=user.id,
                store_id=store.id,
                purpose="receipt",
                storage_key=f"test/{index}",
                content_type="image/png",
                size=1,
                sha256=str(index) * 64,
            )
            for index in (1, 2)
        ]
        session.add_all(files)
        await session.flush()
        payment = Payment(
            user_id=user.id,
            store_id=store.id,
            purpose="wallet_topup",
            provider="manual_card",
            amount=5_000,
            currency="IRT",
            status=initial_status,
            receipt_file_id=files[0].id if initial_status == "awaiting_review" else None,
            meta={"sentinel": "original"},
        )
        session.add(payment)
        await session.commit()
        return payment.id, files[0].id, files[1].id, store.id, user.id


@pytest.mark.parametrize("initial_status", ["pending", "awaiting_review"])
@pytest.mark.parametrize("decision", ["succeeded", "failed"])
async def test_stale_upload_cannot_replace_a_settled_payment(initial_status, decision):
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        payment_id, original_file, replacement_file, store_id, user_id = await _payment_and_receipts(factory, initial_status)
        async with factory() as uploader, factory() as reviewer:
            stale = await uploader.get(Payment, payment_id)
            assert stale.status == initial_status
            if decision == "succeeded":
                await payments.mark_succeeded(reviewer, payment_id)
            else:
                await payments.mark_failed(reviewer, payment_id)
            error = None
            try:
                await payments.attach_receipt(uploader, stale, replacement_file, {"source": "customer"})
            except AppError as exc:
                error = exc
            await uploader.rollback()

        async with factory() as check:
            current = await check.get(Payment, payment_id)
            assert current.status == decision
            assert current.receipt_file_id == (original_file if initial_status == "awaiting_review" else None)
            assert current.meta == {"sentinel": "original"}
            wallet = await check.scalar(select(Wallet).where(Wallet.store_id == store_id, Wallet.user_id == user_id))
            assert (wallet.balance if wallet else 0) == (5_000 if decision == "succeeded" else 0)
        assert error is not None and error.code == "INVALID_PAYMENT_STATE"


async def test_upload_waits_for_a_payment_decision_before_rechecking_status():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        payment_id, _, replacement_file, _, _ = await _payment_and_receipts(factory, "pending")
        async with factory() as uploader, factory() as reviewer:
            stale = await uploader.get(Payment, payment_id)
            current = await reviewer.get(Payment, payment_id, with_for_update=True)
            task = asyncio.create_task(payments.attach_receipt(uploader, stale, replacement_file, {"source": "customer"}))
            try:
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.3)
            finally:
                current.status = "succeeded"
                await reviewer.commit()
            with pytest.raises(AppError) as exc:
                await asyncio.wait_for(task, timeout=5)
            assert exc.value.code == "INVALID_PAYMENT_STATE"
            await uploader.rollback()

        async with factory() as check:
            assert (await check.get(Payment, payment_id)).status == "succeeded"
