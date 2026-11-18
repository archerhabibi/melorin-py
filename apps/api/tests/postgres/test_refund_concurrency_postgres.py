"""Durable refund workflow (M-10) under real row locks: only the PostgreSQL lane can prove these.

Several independent sessions refund the same payment at once while the gateway is slow (so the calls really overlap).
The gateway must be called once, the wallet reversed once, and the losers must get a clean REFUND_IN_PROGRESS.
"""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, make_user, open_schema_engine, pg_url
from melorin.core.errors import AppError
from melorin.kernel.models.payments import Payment, RefundOperation
from melorin.kernel.models.stores import StorePaymentConfiguration
from melorin.kernel.models.wallet import LedgerTransaction
from melorin.modules.payments import service as payments
from melorin.modules.payments.adapters import registry
from melorin.modules.payments.adapters.base import CallbackResult, IntentResult, RefundResult
from melorin.modules.wallet import service as wallet

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL"),
]


class SlowGateway:
    name = "slow_gw"
    requires_review = False

    def __init__(self, delay: float = 0.4):
        self.delay = delay
        self.refunds = 0

    async def create_payment_intent(self, payment, *, callback_url, settings):
        return IntentResult(instructions={"type": "redirect", "url": callback_url}, external_ref=f"AUTH-{payment.id.hex[:8]}")

    async def verify_callback(self, params, payment, *, settings):
        return CallbackResult(str(payment.id), params.get("Authority"), True, dict(params))

    async def query_payment_status(self, payment, *, settings):
        return payment.status

    async def refund(self, payment, *, settings):
        self.refunds += 1
        await asyncio.sleep(self.delay)
        return RefundResult(external_ref="RF-SLOW", status="succeeded", raw={"ok": True})

    def normalize_status(self, raw):
        return raw


async def _succeeded_payment(factory):
    async with factory() as s:
        store, user, admin = await make_store(s), await make_user(s), await make_user(s, super_admin=True)
        s.add(StorePaymentConfiguration(store_id=store.id, provider="slow_gw", is_enabled=True, public_config={}))
        await s.flush()
        p, _ = await payments.create_intent(
            s, user=user, store=store, amount=5_000, provider="slow_gw", idempotency_key="k1", callback_base="https://shop.test"
        )
        await payments.mark_succeeded(s, p.id)
        await s.commit()
        return p.id, store.id, user.id, admin.id


async def _refund(factory, payment_id, admin_id):
    async with factory() as s:
        try:
            await payments.refund_payment(s, payment_id, actor_id=admin_id, reason="concurrent")
            return "ok"
        except AppError as exc:
            await s.rollback()
            return exc.code


async def test_concurrent_refunds_call_the_gateway_once_and_reverse_the_wallet_once(monkeypatch):
    gw = SlowGateway()
    monkeypatch.setitem(registry._ADAPTERS, gw.name, gw)
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        payment_id, store_id, user_id, admin_id = await _succeeded_payment(factory)

        results = await asyncio.gather(*[_refund(factory, payment_id, admin_id) for _ in range(5)])

        assert gw.refunds == 1
        assert results.count("ok") >= 1
        assert set(results) <= {"ok", "REFUND_IN_PROGRESS"}, results
        async with factory() as s:
            assert (await s.get(Payment, payment_id)).status == "refunded"
            op = await s.scalar(select(RefundOperation).where(RefundOperation.payment_id == payment_id))
            assert (op.status, op.external_ref, op.attempts) == ("succeeded", "RF-SLOW", 1)
            assert (await wallet.get_wallet(s, user_id, store_id)).balance == 0
            reversals = await s.scalar(
                select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.payment_id == payment_id)
            )
            assert reversals == 2  # the top-up and exactly one reversal


async def test_repeated_refund_after_success_is_a_noop_on_real_locks(monkeypatch):
    gw = SlowGateway(delay=0)
    monkeypatch.setitem(registry._ADAPTERS, gw.name, gw)
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        payment_id, store_id, user_id, admin_id = await _succeeded_payment(factory)
        assert await _refund(factory, payment_id, admin_id) == "ok"
        assert await _refund(factory, payment_id, admin_id) == "ok"
        assert gw.refunds == 1
