"""M7.1: payment service against real tables - intent idempotency, callbacks (success, duplicate, tampered),
review approval, failure and refund. A fake gateway adapter is plugged in through the registry."""

import uuid

import pytest
from sqlalchemy import func, select

from _db import make_store, make_user, open_session
from melorin.core.errors import AppError
from melorin.modules.payments import service as payments
from melorin.modules.payments.adapters import registry
from melorin.modules.payments.adapters.base import CallbackResult, IntentResult, RefundResult
from melorin.kernel.models.payments import Payment, PaymentAttempt
from melorin.kernel.models.stores import StorePaymentConfiguration
from melorin.kernel.models.system import FeatureFlag, FileObject
from melorin.modules.wallet import service as wallet
from melorin.kernel.models.wallet import LedgerTransaction


class FakeGateway:
    name = "fake_gw"
    requires_review = False

    def __init__(self):
        self.refunds = 0
        self.fail_refund = False
        self.intents = 0

    async def create_payment_intent(self, payment, *, callback_url, settings):
        self.intents += 1
        return IntentResult(instructions={"type": "redirect", "url": callback_url}, external_ref=f"AUTH-{payment.id.hex[:8]}")

    async def verify_callback(self, params, payment, *, settings):
        ok = params.get("Status") == "OK" and params.get("Authority") == payment.external_ref
        return CallbackResult(str(payment.id), params.get("Authority"), ok, dict(params))

    async def query_payment_status(self, payment, *, settings):
        return payment.status

    async def refund(self, payment, *, settings):
        if self.fail_refund:
            raise RuntimeError("gateway down")
        self.refunds += 1
        return RefundResult(external_ref="RF-1", status="succeeded", raw={"ok": True})

    def normalize_status(self, raw):
        return raw


@pytest.fixture
def gateway(monkeypatch):
    gw = FakeGateway()
    monkeypatch.setitem(registry._ADAPTERS, gw.name, gw)
    return gw


async def _setup(s, *, enabled=True, public=None):
    store = await make_store(s)
    user = await make_user(s)
    s.add(StorePaymentConfiguration(store_id=store.id, provider="fake_gw", is_enabled=enabled, public_config=public or {}))
    await s.flush()
    return store, user


async def _intent(s, store, user, *, amount=5_000, key="idem-1", provider="fake_gw"):
    return await payments.create_intent(
        s, user=user, store=store, amount=amount, provider=provider, idempotency_key=key, callback_base="https://shop.test"
    )


async def _balance(s, user, store):
    return (await wallet.get_wallet(s, user.id, store.id)).balance


async def test_create_intent_persists_pending_payment_with_external_ref_and_callback_url(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        p, instructions = await _intent(s, store, user)
        assert p.status == "pending" and p.amount == 5_000 and p.currency == "IRT"
        assert p.external_ref.startswith("AUTH-")
        assert instructions["url"] == f"https://shop.test/api/v1/payments/callbacks/fake_gw?pid={p.id}"
        attempts = (await s.scalars(select(PaymentAttempt).where(PaymentAttempt.payment_id == p.id))).all()
        assert [a.result for a in attempts] == ["ok"]


async def test_same_idempotency_key_returns_same_payment_without_a_second_gateway_call(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        first, _ = await _intent(s, store, user)
        second, _ = await _intent(s, store, user)
        assert first.id == second.id and gateway.intents == 1


async def test_reusing_an_idempotency_key_with_another_amount_is_a_409(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        await _intent(s, store, user, amount=5_000)
        with pytest.raises(AppError) as exc:
            await _intent(s, store, user, amount=6_000)
        assert exc.value.code == "IDEMPOTENCY_KEY_REUSE" and exc.value.status == 409


@pytest.mark.parametrize("amount", [0, -10])
async def test_non_positive_amounts_are_rejected(gateway, amount):
    async with open_session() as s:
        store, user = await _setup(s)
        with pytest.raises(AppError) as exc:
            await _intent(s, store, user, amount=amount)
        assert exc.value.code == "BAD_AMOUNT"


async def test_min_and_max_limits_from_store_configuration_are_enforced(gateway):
    async with open_session() as s:
        store, user = await _setup(s, public={"min_amount": 1_000, "max_amount": 10_000})
        with pytest.raises(AppError) as low:
            await _intent(s, store, user, amount=999, key="a")
        with pytest.raises(AppError) as high:
            await _intent(s, store, user, amount=10_001, key="b")
        assert low.value.code == high.value.code == "BAD_AMOUNT"
        p, _ = await _intent(s, store, user, amount=10_000, key="c")
        assert p.amount == 10_000


async def test_disabled_payment_method_and_kill_switch_block_new_intents(gateway):
    async with open_session() as s:
        store, user = await _setup(s, enabled=False)
        with pytest.raises(AppError) as exc:
            await _intent(s, store, user)
        assert exc.value.code == "PAYMENT_METHOD_DISABLED"
    async with open_session() as s:
        store, user = await _setup(s)
        s.add(FeatureFlag(key="payment", scope_type="global", scope_id=None, enabled=False))
        await s.flush()
        with pytest.raises(AppError) as exc:
            await _intent(s, store, user)
        assert exc.value.code == "FEATURE_DISABLED" and exc.value.status == 503


async def test_only_wallet_topups_are_accepted_and_unknown_gateway_is_rejected(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        with pytest.raises(AppError) as exc:
            await payments.create_intent(s, user=user, store=store, amount=1, provider="fake_gw", idempotency_key="k", purpose="order")
        assert exc.value.code == "WALLET_ONLY"
        with pytest.raises(AppError) as exc:
            await _intent(s, store, user, provider="nope", key="k2")
        assert exc.value.code == "GATEWAY_UNKNOWN"


async def test_gateway_failure_on_create_is_recorded_and_reraised(gateway, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("gateway 500")

    monkeypatch.setattr(gateway, "create_payment_intent", boom)
    async with open_session() as s:
        store, user = await _setup(s)
        with pytest.raises(RuntimeError):
            await _intent(s, store, user)
        p = await s.scalar(select(Payment))
        assert p.meta["external_operation"] == "create_failed" and p.status == "pending"
        assert (await s.scalar(select(PaymentAttempt.result).where(PaymentAttempt.payment_id == p.id))) == "failed"


# ------------------------------------------------------------- callbacks


async def test_successful_callback_credits_the_wallet_exactly_once(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        p, _ = await _intent(s, store, user)
        params = {"pid": str(p.id), "Status": "OK", "Authority": p.external_ref}
        done = await payments.handle_callback(s, "fake_gw", params)
        assert done.status == "succeeded"
        assert await _balance(s, user, store) == 5_000
        tx = await wallet.find_tx(s, f"payment:{p.id}")
        assert tx.kind == "topup" and tx.payment_id == p.id


async def test_duplicate_callback_is_acknowledged_and_never_double_credits(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        p, _ = await _intent(s, store, user)
        params = {"pid": str(p.id), "Status": "OK", "Authority": p.external_ref}
        await payments.handle_callback(s, "fake_gw", params)
        again = await payments.handle_callback(s, "fake_gw", params)
        assert again.status == "succeeded"
        assert await _balance(s, user, store) == 5_000
        results = (
            await s.scalars(select(PaymentAttempt.result).where(PaymentAttempt.payment_id == p.id, PaymentAttempt.action == "callback"))
        ).all()
        assert sorted(results) == ["duplicate", "ok"]
        assert (await s.scalar(select(func.count()).select_from(LedgerTransaction))) == 1


async def test_tampered_authority_fails_the_payment_and_credits_nothing(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        p, _ = await _intent(s, store, user)
        res = await payments.handle_callback(s, "fake_gw", {"pid": str(p.id), "Status": "OK", "Authority": "FORGED"})
        assert res.status == "failed"
        assert await _balance(s, user, store) == 0


async def test_user_cancelled_callback_fails_without_credit(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        p, _ = await _intent(s, store, user)
        res = await payments.handle_callback(s, "fake_gw", {"pid": str(p.id), "Status": "NOK", "Authority": p.external_ref})
        assert res.status == "failed" and await _balance(s, user, store) == 0


async def test_late_success_callback_after_failure_is_rejected_for_system_actor(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        p, _ = await _intent(s, store, user)
        await payments.handle_callback(s, "fake_gw", {"pid": str(p.id), "Status": "NOK", "Authority": p.external_ref})
        with pytest.raises(AppError) as exc:
            await payments.handle_callback(s, "fake_gw", {"pid": str(p.id), "Status": "OK", "Authority": p.external_ref})
        assert exc.value.code == "INVALID_PAYMENT_STATE" and exc.value.status == 409
        assert await _balance(s, user, store) == 0


@pytest.mark.parametrize("pid", [None, "not-a-uuid", str(uuid.uuid4())])
async def test_callback_with_missing_malformed_or_unknown_payment_id_is_404(gateway, pid):
    async with open_session() as s:
        await _setup(s)
        with pytest.raises(AppError) as exc:
            await payments.handle_callback(s, "fake_gw", {"pid": pid, "Status": "OK"})
        assert exc.value.code == "PAYMENT_NOT_FOUND" and exc.value.status == 404


async def test_callback_cannot_be_replayed_against_another_provider(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        p, _ = await _intent(s, store, user)
        with pytest.raises(AppError) as exc:
            await payments.handle_callback(s, "zarinpal", {"pid": str(p.id), "Status": "OK", "Authority": p.external_ref})
        assert exc.value.code == "PAYMENT_NOT_FOUND"


# -------------------------------------------------- review / failure / refund


async def test_admin_approval_credits_once_and_records_reviewer(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        admin = await make_user(s, super_admin=True)
        p, _ = await _intent(s, store, user)
        await payments.mark_succeeded(s, p.id, actor_id=admin.id, actor_type="admin")
        await payments.mark_succeeded(s, p.id, actor_id=admin.id, actor_type="admin")
        assert await _balance(s, user, store) == 5_000
        assert p.reviewed_by == admin.id and p.reviewed_at is not None


async def test_admin_may_approve_a_previously_failed_payment_but_system_may_not(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        admin = await make_user(s, super_admin=True)
        p, _ = await _intent(s, store, user)
        await payments.mark_failed(s, p.id, reason="receipt unreadable")
        with pytest.raises(AppError):
            await payments.mark_succeeded(s, p.id)
        await payments.mark_succeeded(s, p.id, actor_id=admin.id, actor_type="admin")
        assert await _balance(s, user, store) == 5_000


async def test_mark_failed_is_a_noop_on_succeeded_payments(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        p, _ = await _intent(s, store, user)
        await payments.mark_succeeded(s, p.id)
        res = await payments.mark_failed(s, p.id, reason="late")
        assert res.status == "succeeded" and await _balance(s, user, store) == 5_000


async def test_refund_reverses_the_wallet_credit_once_and_calls_gateway_once(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        admin = await make_user(s, super_admin=True)
        p, _ = await _intent(s, store, user)
        await payments.mark_succeeded(s, p.id)
        refunded = await payments.refund_payment(s, p.id, actor_id=admin.id, reason="customer request")
        again = await payments.refund_payment(s, p.id, actor_id=admin.id)
        assert refunded.status == again.status == "refunded"
        assert gateway.refunds == 1
        assert await _balance(s, user, store) == 0
        assert refunded.meta["refund_external_ref"] == "RF-1"


async def test_refund_of_a_non_succeeded_payment_is_a_409(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        admin = await make_user(s, super_admin=True)
        p, _ = await _intent(s, store, user)
        with pytest.raises(AppError) as exc:
            await payments.refund_payment(s, p.id, actor_id=admin.id)
        assert exc.value.code == "INVALID_PAYMENT_STATE"


async def test_gateway_refund_failure_keeps_money_in_the_wallet_and_marks_the_operation_failed(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        admin = await make_user(s, super_admin=True)
        p, _ = await _intent(s, store, user)
        await payments.mark_succeeded(s, p.id)
        gateway.fail_refund = True
        with pytest.raises(RuntimeError):
            await payments.refund_payment(s, p.id, actor_id=admin.id)
        await s.refresh(p)
        assert p.status == "succeeded" and p.meta["refund_operation"] == "failed"
        assert await _balance(s, user, store) == 5_000


async def test_refund_of_unknown_payment_is_404(gateway):
    async with open_session() as s:
        await _setup(s)
        with pytest.raises(AppError) as exc:
            await payments.refund_payment(s, uuid.uuid4(), actor_id=uuid.uuid4())
        assert exc.value.status == 404


async def test_receipt_upload_moves_manual_payment_to_review_and_rejects_other_providers(gateway):
    async with open_session() as s:
        store, user = await _setup(s)
        p, _ = await _intent(s, store, user)
        with pytest.raises(AppError) as exc:  # fake_gw is not a manual provider
            await payments.attach_receipt(s, p, uuid.uuid4())
        assert exc.value.code == "INVALID_PAYMENT_STATE"
        p.provider = "manual_card"
        receipt = FileObject(
            owner_user_id=user.id,
            store_id=store.id,
            purpose="receipt",
            storage_key="r/1",
            content_type="image/png",
            size=1,
            sha256="0" * 64,
        )
        s.add(receipt)
        await s.flush()  # a real file row: PostgreSQL enforces the receipt_file_id foreign key
        await payments.attach_receipt(s, p, receipt.id)
        assert p.status == "awaiting_review"


async def test_can_review_allows_super_admin_and_the_owner_of_a_reseller_store_only(gateway):
    async with open_session() as s:
        owner, stranger = await make_user(s), await make_user(s)
        admin = await make_user(s, super_admin=True)
        reseller = await make_store(s, kind="reseller", owner=owner)
        main = await make_store(s)
        p_res = Payment(
            user_id=stranger.id,
            store_id=reseller.id,
            purpose="wallet_topup",
            provider="manual_card",
            amount=1,
            currency="IRT",
            status="pending",
        )
        p_main = Payment(
            user_id=stranger.id,
            store_id=main.id,
            purpose="wallet_topup",
            provider="manual_card",
            amount=1,
            currency="IRT",
            status="pending",
        )
        assert await payments.can_review(s, admin, p_main)
        assert await payments.can_review(s, owner, p_res)
        assert not await payments.can_review(s, stranger, p_res)
        assert not await payments.can_review(s, owner, p_main)
