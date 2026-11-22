import datetime as dt
import json
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events, flags
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.core.invariants import require
from melorin.core.crypto import decrypt
from melorin.domain.order_state import PaymentStatus
from melorin.kernel.models.identity import User
from melorin.modules.payments import receipt_fingerprints
from melorin.modules.payments.adapters.registry import get_adapter
from melorin.modules.payments.gateway_catalog import validate_destination
from melorin.kernel.models.payments import Payment, PaymentAttempt, RefundOperation
from melorin.kernel.models.stores import Store, StorePaymentConfiguration
from melorin.modules.wallet import service as wallet

P = PaymentStatus
log = logging.getLogger("melorin.payments")


MAX_DUPLICATE_ATTEMPTS = 5  # duplicate-callback audit rows kept per payment
_MAX_PARAMS, _MAX_VALUE_LEN = 20, 200


def bounded_callback_params(params: dict) -> dict:
    """Trace-sized copy of untrusted callback params: few keys, short strings (never the raw request)."""
    return {str(k)[:50]: str(v)[:_MAX_VALUE_LEN] for k, v in list(params.items())[:_MAX_PARAMS]}


_CURRENCY_CHECKED = frozenset({"zarinpal", "external_gateway", "crypto", "telegram_stars"})
CREATE_INTENT_IN_FLIGHT_SECONDS = 120  # comfortably above the gateway adapters' 15-second HTTP timeout


def _check_currency(provider: str, currency: str) -> None:
    if provider not in _CURRENCY_CHECKED:
        return
    try:
        validate_destination(provider, currency)
    except ValueError as exc:
        raise AppError("PAYMENT_CURRENCY_UNSUPPORTED", "این درگاه با ارز فروشگاه سازگار نیست.", 400) from exc


def _store_configured_settings(cfg: StorePaymentConfiguration, provider: str, *, require_enabled: bool = True) -> dict:
    """Read a store's own destination; disabling new charges does not erase credentials for existing operations."""
    if require_enabled and not cfg.is_enabled:
        raise AppError("PAYMENT_METHOD_DISABLED", "این روش شارژ در این فروشگاه فعال نیست.", 400)
    public = dict(cfg.public_config or {})
    secret = json.loads(decrypt(cfg.secret_enc) or "{}") if cfg.secret_enc else {}
    if provider == "manual_card" and not all(public.get(k) for k in ("card_number", "holder")):
        raise AppError("PAYMENT_DESTINATION_MISSING", "مقصد پرداخت کارت‌به‌کارت برای این فروشگاه کامل نیست.", 409)
    if provider == "zarinpal" and not secret.get("merchant_id") and not secret.get("api_key"):
        raise AppError("PAYMENT_DESTINATION_MISSING", "مقصد پرداخت این درگاه پیکربندی نشده است.", 409)
    return {
        "card.info": public,
        f"gateway.{provider}": {**public, **secret},
        # NEVER merge ``secret`` here: this dict is echoed to the customer as payment instructions (V-15). Gateways that need
        # credentials (zarinpal) read ``gateway.{provider}`` server-side and never put it in ``instructions``.
        f"destination.{provider}": dict(public),
        "limits": public,
    }


async def store_payment_settings(session: AsyncSession, store: Store, provider: str, *, require_enabled: bool = True) -> dict:
    """Read store-owned payment settings.

    ``require_enabled`` gates creation of new payment intents. Existing callbacks and
    refunds must keep access to the configured credentials after an admin disables
    new charges for that provider.
    """
    cfg = await session.scalar(
        select(StorePaymentConfiguration).where(
            StorePaymentConfiguration.store_id == store.id, StorePaymentConfiguration.provider == provider
        )
    )
    _check_currency(provider, store.currency)
    if cfg is not None:
        return _store_configured_settings(cfg, provider, require_enabled=require_enabled)
    raise AppError("PAYMENT_METHOD_DISABLED", "روش شارژ برای این فروشگاه پیکربندی نشده است.", 400)


def _has_external_side_effect(adapter) -> bool:
    """Only adapters that call a remote provider can double-charge on a blind retry; local ones (manual card) are replay-safe."""
    return bool(getattr(adapter, "create_has_external_side_effect", True))


def _is_definitive_rejection(exc: Exception) -> bool:
    """The provider ANSWERED and refused (or the request never left): no intent can exist remotely, so a retry is safe.
    Timeouts, transport errors and anything unrecognised stay unknown."""
    if isinstance(exc, AppError):
        return True
    kind = getattr(exc, "kind", None)
    return getattr(kind, "name", "") == "PERMANENT"


def _mark_unknown(p: Payment, exc: Exception | None = None) -> None:
    meta = {**(p.meta or {}), "external_operation": "create_unknown", "reconciliation_required": True}
    if exc is not None:
        meta["error_type"] = type(exc).__name__
    p.meta = meta


def _lease_expired(meta: dict) -> bool:
    raw = meta.get("create_started_at")
    try:
        if not isinstance(raw, str):
            return True
        started = dt.datetime.fromisoformat(raw)
        if started.tzinfo is None:
            started = started.replace(tzinfo=dt.timezone.utc)
        return (utcnow() - started).total_seconds() > CREATE_INTENT_IN_FLIGHT_SECONDS
    except ValueError:
        return True


def _unknown_error() -> AppError:
    return AppError(
        "PAYMENT_INTENT_OUTCOME_UNKNOWN",
        "نتیجه ایجاد پرداخت در درگاه مشخص نیست؛ برای جلوگیری از پرداخت تکراری، درخواست دوباره ارسال نمی‌شود. با پشتیبانی تماس بگیرید.",
        409,
    )


def _callback_url(base: str, provider: str, payment_id: uuid.UUID) -> str:
    return f"{base}/api/v1/payments/callbacks/{provider}?pid={payment_id}"


async def _run_create(session: AsyncSession, p: Payment, adapter, *, callback_url: str, settings: dict) -> tuple[Payment, dict]:
    """The one place that calls the adapter. ``p`` is already committed as ``creating``; no DB lock is held across the call."""
    try:
        res = await adapter.create_payment_intent(p, callback_url=callback_url, settings=settings)
    except Exception as exc:
        log.warning("payment create failed payment=%s provider=%s", p.id, p.provider, exc_info=True)
        base = {"create_started_at": (p.meta or {}).get("create_started_at")}
        if _is_definitive_rejection(exc) or not _has_external_side_effect(adapter):
            # Provider refused, or the call is local: nothing can exist remotely, so the same key may safely retry.
            p.meta = {**base, "external_operation": "create_failed", "reconciliation_required": False, "error_type": type(exc).__name__}
            session.add(PaymentAttempt(payment_id=p.id, action="create", result="failed", data={"error_type": type(exc).__name__}))
            await session.commit()
            raise
        # Timeout/transport error: the provider may have accepted the request. Never blind-retry; require reconciliation.
        p.meta = {**base, "external_operation": "create_unknown", "reconciliation_required": True, "error_type": type(exc).__name__}
        session.add(PaymentAttempt(payment_id=p.id, action="create", result="unknown", data={"error_type": type(exc).__name__}))
        await session.commit()
        raise AppError(
            "PAYMENT_INTENT_OUTCOME_UNKNOWN",
            "نتیجه ایجاد پرداخت در درگاه مشخص نیست؛ برای جلوگیری از پرداخت تکراری، درخواست را دوباره ارسال نکنید و با پشتیبانی تماس بگیرید.",
            503,
        ) from exc
    p.external_ref = res.external_ref
    p.meta = {"external_operation": "created", "instructions": res.instructions, "reconciliation_required": False}
    session.add(PaymentAttempt(payment_id=p.id, action="create", result="ok", data={"external_ref": res.external_ref}))
    await session.commit()
    return p, res.instructions


async def _replay_existing(
    session: AsyncSession, existing: Payment, adapter, *, callback_url: str, settings_loader
) -> tuple[Payment, dict]:
    """Same idempotency key seen again. Returns the stored intent, or fails closed when creating it again could charge twice."""
    meta = existing.meta or {}
    operation = meta.get("external_operation")
    # Legacy rows (before ``external_operation`` existed) that already hold a provider reference or instructions are complete.
    if operation == "created" or (operation is None and (existing.external_ref or meta.get("instructions"))):
        return existing, meta.get("instructions", {})
    if existing.status != P.PENDING:
        raise AppError("PAYMENT_INTENT_UNAVAILABLE", "وضعیت درخواست پرداخت قابل استفاده نیست؛ یک درخواست جدید ثبت کنید.", 409)
    if operation == "creating" and not _lease_expired(meta):
        raise AppError(
            "PAYMENT_INTENT_IN_PROGRESS", "درخواست پرداخت با همین کلید هنوز در حال پردازش است؛ کمی بعد وضعیت آن را بررسی کنید.", 409
        )
    safe_to_retry = not _has_external_side_effect(adapter) or (
        operation == "create_failed" and meta.get("reconciliation_required") is False
    )
    if safe_to_retry:
        # Atomic claim: only one concurrent replay moves the row back to ``creating`` and may call the adapter.
        claimed = await session.get(Payment, existing.id, with_for_update=True, populate_existing=True)
        if claimed is None:
            raise AppError("PAYMENT_NOT_FOUND", "پرداخت یافت نشد.", 404)
        cm = claimed.meta or {}
        if cm.get("external_operation") not in (operation,) or claimed.external_ref:
            raise AppError("PAYMENT_INTENT_IN_PROGRESS", "درخواست پرداخت با همین کلید در حال پردازش است.", 409)
        claimed.meta = {"external_operation": "creating", "create_started_at": utcnow().isoformat()}
        await session.commit()
        return await _run_create(session, claimed, adapter, callback_url=callback_url, settings=await settings_loader())
    # creating (lease expired) / create_unknown / legacy: fail closed and flag for reconciliation.
    if operation != "create_unknown" or not meta.get("reconciliation_required"):
        _mark_unknown(existing)
        await session.commit()
    raise _unknown_error()


async def create_intent(
    session: AsyncSession,
    *,
    user: User,
    store: Store,
    amount: int,
    provider: str,
    idempotency_key: str,
    callback_base: str = "",
    purpose: str = "wallet_topup",
) -> tuple[Payment, dict]:
    """Wallet top-up of THIS store only. Money goes to this store's own destination; never to another store.

    Crash/timeout safety: the row is committed as ``creating`` BEFORE the provider call. A repeated key never issues a second
    provider call unless the adapter is side-effect free or the provider definitively refused the first one.
    """
    existing = await session.scalar(
        select(Payment).where(Payment.user_id == user.id, Payment.store_id == store.id, Payment.idempotency_key == idempotency_key)
    )
    if existing:
        if existing.amount != amount or existing.provider != provider or existing.purpose != purpose:
            raise AppError("IDEMPOTENCY_KEY_REUSE", "کلید idempotency با درخواست دیگری استفاده شده است.", 409)
        adapter = get_adapter(existing.provider)

        async def _settings() -> dict:
            return await store_payment_settings(session, store, provider)

        return await _replay_existing(
            session, existing, adapter, callback_url=_callback_url(callback_base, provider, existing.id), settings_loader=_settings
        )
    if purpose != "wallet_topup":
        raise AppError("WALLET_ONLY", "پرداخت فقط برای شارژ کیف پول است؛ خرید از کیف پول انجام می‌شود.", 400)
    await flags.ensure_enabled(session, "payment", store_id=store.id)
    if amount <= 0:
        raise AppError("BAD_AMOUNT", "مبلغ نامعتبر است.", 400)
    adapter = get_adapter(provider)
    cfg = await store_payment_settings(session, store, provider)
    limits = cfg.get("limits") or {}
    if limits.get("min_amount") and amount < int(limits["min_amount"]):
        raise AppError("BAD_AMOUNT", "مبلغ کمتر از حداقل مجاز است.", 400)
    if limits.get("max_amount") and amount > int(limits["max_amount"]):
        raise AppError("BAD_AMOUNT", "مبلغ بیشتر از حداکثر مجاز است.", 400)
    p = Payment(
        user_id=user.id,
        store_id=store.id,
        purpose="wallet_topup",
        provider=provider,
        amount=amount,
        currency=store.currency,
        status=P.PENDING,
        idempotency_key=idempotency_key,
        meta={"external_operation": "creating", "create_started_at": utcnow().isoformat()},
    )
    session.add(p)
    try:
        await session.flush()
        await session.commit()  # persist before the external call
    except IntegrityError:
        await session.rollback()
        winner = await session.scalar(
            select(Payment).where(Payment.user_id == user.id, Payment.store_id == store.id, Payment.idempotency_key == idempotency_key)
        )
        if winner is None:
            raise
        if winner.amount != amount or winner.provider != provider or winner.purpose != purpose:
            raise AppError("IDEMPOTENCY_KEY_REUSE", "کلید idempotency با درخواست دیگری استفاده شده است.", 409) from None

        async def _settings_again() -> dict:
            return cfg

        # A concurrent request with the same key won the insert; it owns the provider call (fresh lease => IN_PROGRESS).
        return await _replay_existing(
            session, winner, adapter, callback_url=_callback_url(callback_base, provider, winner.id), settings_loader=_settings_again
        )
    return await _run_create(session, p, adapter, callback_url=_callback_url(callback_base, provider, p.id), settings=cfg)


async def attach_receipt(
    session: AsyncSession,
    payment: Payment,
    file_id: uuid.UUID,
    claim: dict | None = None,
    duplicate: dict | None = None,
    *,
    read_later: bool = False,
    origin: str | None = None,
) -> None:
    """``claim`` = what the customer read off the receipt (time, reference, source card tail); used by bank-SMS matching.

    ``duplicate`` = summary of earlier payments that used the same picture (see ``receipt_fingerprints.summarize``); it is
    kept on the payment and added to the reviewers' notice. The upload itself was already accepted by the store's policy.

    ``read_later`` queues the automatic reading of the picture (OCR/vision) for the worker; ``claim`` then holds only what the
    customer typed and is completed by ``ocr_job.run`` (V01 V-21). A replaced receipt discards the older reading.
    """
    if payment.provider != "manual_card" or payment.status not in (P.PENDING, P.AWAITING_REVIEW):
        raise AppError("INVALID_PAYMENT_STATE", "برای این پرداخت امکان ارسال رسید نیست.", 409)
    payment.receipt_file_id = file_id
    payment.meta = {**(payment.meta or {}), "receipt_attached_at": utcnow().isoformat()}  # start of the grace clock
    if claim:
        payment.meta = {**payment.meta, "receipt_claim": claim}
    meta = {
        k: v for k, v in payment.meta.items() if k not in ("receipt_duplicate", "receipt_ocr", "receipt_origin")
    }  # a replaced receipt starts clean
    if origin:
        meta["receipt_origin"] = origin  # keyed tag of the uploader's network (provisional.origin_tag), never the raw address
    meta = {**meta, "receipt_duplicate": duplicate} if duplicate else meta
    if read_later:
        from melorin.modules.payments import ocr_job  # deferred: ocr_job imports the bank-SMS package, which imports this module

        typed = {k: v for k, v in (claim or {}).items() if k in ("paid_at", "reference", "source_card_last4")}
        meta["receipt_ocr"] = ocr_job.pending_state(file_id)
        await events.emit(
            session,
            events.RECEIPT_OCR,
            {"payment_id": payment.id, "store_id": payment.store_id, "file_id": file_id, "typed": typed},
            dedup_key=f"receipt-ocr:{payment.id}:{file_id}",
        )
    payment.meta = meta
    payment.status = P.AWAITING_REVIEW
    note = receipt_fingerprints.warning_text(duplicate)
    await events.emit(
        session,
        events.EVENT_CENTER,
        {
            "store_id": payment.store_id,
            "topic": "payments",
            "text": f"🧾 رسید جدید برای بررسی\nمبلغ: {payment.amount:,}\nشناسه: {payment.id}" + (f"\n{note}" if note else ""),
        },
    )
    await session.commit()


async def mark_succeeded(session: AsyncSession, payment_id: uuid.UUID, *, actor_id=None, actor_type="system", note=None) -> Payment:
    """Idempotent: duplicate callbacks/approvals never double-credit (row lock + ledger idempotency key)."""
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if p is None:
        raise AppError("PAYMENT_NOT_FOUND", "پرداخت یافت نشد.", 404)
    if p.status == P.SUCCEEDED:
        return p
    if p.status == P.REFUNDED:  # an admin override must not resurrect a refunded payment (ledger shows a reversal)
        raise AppError("INVALID_PAYMENT_STATE", "این پرداخت استرداد شده و قابل تأیید مجدد نیست.", 409)
    if p.status in (P.FAILED, P.CANCELLED) and actor_type != "admin":
        raise AppError("INVALID_PAYMENT_STATE", "وضعیت پرداخت نامعتبر است.", 409)
    p.status = P.SUCCEEDED
    p.reviewed_by, p.reviewed_at = actor_id, utcnow() if actor_id else None
    w = await wallet.get_wallet(session, p.user_id, p.store_id, currency=p.currency)
    await wallet.post(
        session,
        kind="topup",
        key=f"payment:{p.id}",
        currency=p.currency,
        store_id=p.store_id,
        payment_id=p.id,
        actor_id=actor_id,
        postings=[wallet.Posting(-p.amount, account=wallet.acc_store_topup(p.store_id, p.provider)), wallet.Posting(p.amount, wallet=w)],
        memo="شارژ کیف پول",
    )
    audit.record(
        session,
        "payment.succeeded",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="payment",
        entity_id=p.id,
        store_id=p.store_id,
        data={"amount": p.amount, "note": note},
    )
    await events.emit(session, events.PAYMENT_SUCCEEDED, {"payment_id": p.id, "store_id": p.store_id})
    await events.emit_user_notice(
        session, p.user_id, p.store_id, "payment", "پرداخت تأیید شد", f"پرداخت {p.amount:,} تأیید شد.", dedup_key=f"notify:payment:{p.id}"
    )
    await session.commit()
    return p


async def mark_failed(session: AsyncSession, payment_id: uuid.UUID, *, actor_id=None, reason=None) -> Payment:
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if p is None:
        raise AppError("PAYMENT_NOT_FOUND", "پرداخت یافت نشد.", 404)
    if p.status in (P.SUCCEEDED, P.FAILED):
        if (p.meta or {}).get("provisional", {}).get("state") == "open":
            # The wallet still holds the provisional credit: rejecting must go through provisional.resolve (it reverses the ledger).
            raise AppError("PROVISIONAL_CREDIT_OPEN", "برای این پرداخت اعتبار موقت باز است؛ از مسیر لغو تأیید موقت استفاده کنید.", 409)
        return p
    p.status = P.FAILED
    p.reviewed_by, p.reviewed_at = actor_id, utcnow()
    audit.record(
        session,
        "payment.failed",
        actor_id=actor_id,
        actor_type="admin" if actor_id else "system",
        entity_type="payment",
        entity_id=p.id,
        data={"reason": reason},
    )
    await events.emit(session, events.PAYMENT_FAILED, {"payment_id": p.id, "store_id": p.store_id})
    await events.emit_user_notice(session, p.user_id, p.store_id, "payment", "پرداخت ناموفق", reason or "پرداخت شما تأیید نشد.")
    await session.commit()
    return p


REFUND_LEASE_SECONDS = 180  # > the adapters' HTTP timeouts; a longer silence means the worker died mid-call
REFUND_MAX_ATTEMPTS = 5


def _refund_key(payment_id: uuid.UUID) -> str:
    return f"payment:{payment_id}:refund"


async def _lock_payment(session: AsyncSession, payment_id: uuid.UUID) -> Payment:
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if not p:
        raise AppError("PAYMENT_NOT_FOUND", "پرداخت یافت نشد.", 404)
    return p


async def _get_payment(session: AsyncSession, payment_id: uuid.UUID) -> Payment:
    p = await session.get(Payment, payment_id, populate_existing=True)
    if p is None:
        raise AppError("PAYMENT_NOT_FOUND", "پرداخت یافت نشد.", 404)
    return p


async def _lock_refund_op(session: AsyncSession, payment_id: uuid.UUID) -> RefundOperation | None:
    return await session.scalar(
        select(RefundOperation).where(RefundOperation.payment_id == payment_id).with_for_update().execution_options(populate_existing=True)
    )


def _lease_active(op: RefundOperation) -> bool:
    exp = op.lease_expires_at
    if exp is None:
        return False
    if exp.tzinfo is None:  # SQLite returns naive datetimes
        exp = exp.replace(tzinfo=dt.timezone.utc)
    return exp > utcnow()


def _set_refund_meta(p: Payment, state: str, **extra) -> None:
    p.meta = {**(p.meta or {}), "refund_operation": state, **extra}


async def _claim_refund(session: AsyncSession, payment_id: uuid.UUID, *, actor_id, reason: str | None) -> tuple[RefundOperation, dict, str]:
    """Phase 1 (short transaction): validate, create-or-reclaim the operation, take a lease, COMMIT (drops the row lock)."""
    p = await _lock_payment(session, payment_id)
    if p.status == P.REFUNDED:
        raise _AlreadyRefunded(p)
    if p.status != P.SUCCEEDED:
        raise AppError("INVALID_PAYMENT_STATE", "فقط پرداخت موفق قابل استرداد است.", 409)
    store = await session.get(Store, p.store_id)
    if store is None:
        raise AppError("STORE_NOT_FOUND", "فروشگاه یافت نشد.", 404)
    cfg = await store_payment_settings(session, store, p.provider, require_enabled=False)
    op = await _lock_refund_op(session, p.id)
    if op is None:
        op = RefundOperation(
            payment_id=p.id,
            store_id=p.store_id,
            status="pending",
            amount=p.amount,
            currency=p.currency,
            idempotency_key=_refund_key(p.id),
            requested_by=actor_id,
            reason=(reason or "")[:500] or None,
            started_at=utcnow(),
        )
        session.add(op)
        await session.flush()
    elif op.status == "manual_review":
        raise AppError("REFUND_MANUAL_REVIEW", "این استرداد برای بررسی دستی علامت خورده است.", 409)
    elif op.status == "processing" and _lease_active(op):
        raise AppError("REFUND_IN_PROGRESS", "استرداد در حال انجام است.", 409)
    elif op.status == "processing" and op.external_ref:
        pass  # gateway already refunded; the caller finishes the ledger step without another gateway call
    elif op.status == "processing":
        # lease expired with no recorded gateway outcome: never re-send blindly
        op.status, op.last_error = "manual_review", "gateway outcome unknown after lease expiry"
        _set_refund_meta(p, "manual_review")
        await session.commit()
        raise AppError("REFUND_MANUAL_REVIEW", "نتیجهٔ استرداد نامشخص است؛ بررسی دستی لازم است.", 409)
    if op.attempts >= REFUND_MAX_ATTEMPTS and not op.external_ref:
        op.status, op.last_error = "manual_review", op.last_error or "max attempts reached"
        _set_refund_meta(p, "manual_review")
        await session.commit()
        raise AppError("REFUND_MANUAL_REVIEW", "تعداد تلاش‌ها به سقف رسید؛ بررسی دستی لازم است.", 409)
    op.status = "processing"
    op.attempts += 1
    op.lease_owner = uuid.uuid4().hex
    op.lease_expires_at = utcnow() + dt.timedelta(seconds=REFUND_LEASE_SECONDS)
    _set_refund_meta(p, "pending")
    await session.commit()
    return op, cfg, op.lease_owner


class _AlreadyRefunded(Exception):
    def __init__(self, payment: Payment):
        self.payment = payment


async def _record_refund_failure(session: AsyncSession, payment_id: uuid.UUID, lease: str, exc: Exception) -> None:
    """Phase 2b (failure): release the lease. Money stays in the wallet; NotImplementedError goes to manual review."""
    p = await _lock_payment(session, payment_id)
    op = await _lock_refund_op(session, payment_id)
    unsupported = isinstance(exc, NotImplementedError)
    if op is not None and op.lease_owner == lease:
        op.status = "manual_review" if unsupported else "failed"
        op.last_error = str(exc)[:500]
        op.lease_owner = op.lease_expires_at = None
        op.finished_at = utcnow()
    _set_refund_meta(p, "failed", refund_error=str(exc)[:300])
    session.add(PaymentAttempt(payment_id=p.id, action="refund", result="failed", data={"error": str(exc)[:500]}))
    await session.commit()


async def finalize_refund(
    session: AsyncSession, payment_id: uuid.UUID, *, actor_id=None, reason: str | None = None, raw: dict | None = None
) -> Payment:
    """Phase 3 (short transaction): the gateway outcome is recorded on the operation, so reverse the ledger exactly once
    (idempotency key), mark the payment REFUNDED and close the operation. Safe to call again after a crash."""
    p = await _lock_payment(session, payment_id)
    op = await _lock_refund_op(session, payment_id)
    if op is None or not op.external_ref:
        raise AppError("REFUND_NOT_CONFIRMED", "نتیجهٔ درگاه برای این استرداد ثبت نشده است.", 409)
    if p.status != P.REFUNDED:
        tx = await wallet.find_tx(session, f"payment:{p.id}")
        if p.status != P.SUCCEEDED or tx is None:
            # The gateway already refunded the money, but our books disagree (payment no longer SUCCEEDED, or no ledger credit to
            # reverse). Never mark it REFUNDED on guesswork: park the operation for a human and keep the evidence.
            op.status, op.finished_at = "manual_review", None
            op.last_error = f"cannot finalize: payment status={p.status}, ledger credit={'present' if tx else 'missing'}"
            op.lease_owner = op.lease_expires_at = None
            _set_refund_meta(p, "manual_review")
            audit.record(
                session,
                "payment.refund_needs_review",
                actor_id=actor_id or op.requested_by,
                actor_type="admin",
                entity_type="payment",
                entity_id=p.id,
                store_id=p.store_id,
                data={"detail": op.last_error},
            )
            await session.commit()
            return p
        await wallet.reverse(
            session,
            tx,
            key=_refund_key(p.id),
            kind="topup_refund",
            actor_id=actor_id or op.requested_by,
            memo=reason or op.reason or "استرداد شارژ",
        )
        p.status = P.REFUNDED
        session.add(PaymentAttempt(payment_id=p.id, action="refund", result="ok", data=raw or {"external_ref": op.external_ref}))
        audit.record(
            session,
            "payment.refunded",
            actor_id=actor_id or op.requested_by,
            actor_type="admin",
            entity_type="payment",
            entity_id=p.id,
            store_id=p.store_id,
            data={"reason": reason or op.reason, "external_ref": op.external_ref, "operation_id": str(op.id)},
        )
    op.status, op.finished_at, op.last_error = "succeeded", utcnow(), None
    op.lease_owner = op.lease_expires_at = None
    _set_refund_meta(p, "succeeded", refund_external_ref=op.external_ref)
    await session.commit()
    return p


async def refund_payment(session: AsyncSession, payment_id: uuid.UUID, *, actor_id, reason: str | None = None) -> Payment:
    """Refund the external payment, then reverse its wallet credit once (durable, three short transactions).

    1. claim: lock the payment, create/reclaim the RefundOperation with a lease, commit;
    2. gateway: call the adapter with NO transaction or lock open, then commit its outcome (external_ref) on the operation;
    3. finalize: reverse the ledger (idempotent key), mark REFUNDED, close the operation.
    A crash after 2 is repaired by ``recover_refunds`` (no second gateway call); an unknown gateway outcome goes to
    manual_review instead of being retried blindly.
    """
    try:
        op, cfg, lease = await _claim_refund(session, payment_id, actor_id=actor_id, reason=reason)
    except _AlreadyRefunded as done:
        return done.payment
    p = await _get_payment(session, payment_id)
    if not op.external_ref:
        try:
            result = await get_adapter(p.provider).refund(p, settings=cfg)
        except Exception as exc:
            log.warning("payment refund failed payment=%s provider=%s", payment_id, p.provider, exc_info=True)
            await _record_refund_failure(session, payment_id, lease, exc)
            if isinstance(exc, NotImplementedError):
                # manual card / destination providers have no automatic refund: a clean 409 for the admin, not a 500
                raise AppError(
                    "REFUND_NOT_SUPPORTED",
                    "این روش پرداخت استرداد خودکار ندارد؛ جبران دستی از کیف پول انجام شود.",
                    409,
                ) from exc
            raise
        await _lock_payment(session, payment_id)
        confirmed = require(await _lock_refund_op(session, payment_id), "refund operation")
        confirmed.external_ref = result.external_ref or f"refund-{confirmed.id}"
        await session.commit()  # the gateway outcome is durable BEFORE the ledger changes
        raw = result.raw
    else:
        raw = None
    return await finalize_refund(session, payment_id, actor_id=actor_id, reason=reason, raw=raw)


async def recover_refunds(session: AsyncSession, *, limit: int = 50) -> dict:
    """Worker sweep: finish refunds whose gateway call succeeded but whose ledger step never committed, and park
    operations whose lease expired without a gateway outcome in manual_review (never re-sent blindly)."""
    ops = (
        await session.scalars(
            select(RefundOperation).where(RefundOperation.status == "processing", RefundOperation.lease_expires_at < utcnow()).limit(limit)
        )
    ).all()
    out = {"finalized": 0, "manual_review": 0}
    for stale in [(o.payment_id, o.external_ref) for o in ops]:
        payment_id, ref = stale
        if ref:
            await finalize_refund(session, payment_id)
            out["finalized"] += 1
            continue
        p = await _lock_payment(session, payment_id)
        op = await _lock_refund_op(session, payment_id)
        if op is not None and op.status == "processing" and not op.external_ref and not _lease_active(op):
            op.status, op.last_error = "manual_review", "gateway outcome unknown after lease expiry"
            op.lease_owner = op.lease_expires_at = None
            _set_refund_meta(p, "manual_review")
            out["manual_review"] += 1
        await session.commit()
    return out


async def reconcile_unknown_create(
    session: AsyncSession,
    payment_id: uuid.UUID,
    *,
    action: str,
    actor_id: uuid.UUID,
    external_ref: str | None = None,
    reason: str | None = None,
) -> Payment:
    """Admin resolution of a ``create_unknown`` payment (the only way out; automatic recovery is deliberately absent).

    ``bind``: the admin looked the transaction up at the provider and confirmed it belongs to THIS payment; it is attached and the
    payment becomes a normal pending one, so the customer's callback can verify it. ``abandon``: the provider has no such
    transaction (or it is unwanted); the payment fails and the customer may start over with a new key.
    """
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if p is None:
        raise AppError("PAYMENT_NOT_FOUND", "پرداخت یافت نشد.", 404)
    meta = p.meta or {}
    if meta.get("external_operation") not in ("create_unknown", "creating") or p.status != P.PENDING:
        raise AppError("PAYMENT_NOT_RECONCILABLE", "این پرداخت در وضعیت نتیجهٔ نامعلوم نیست.", 409)
    if action == "bind":
        ref = (external_ref or "").strip()
        if not ref:
            raise AppError("PAYMENT_REFERENCE_REQUIRED", "شناسهٔ تراکنش درگاه لازم است.", 400)
        clash = await session.scalar(
            select(Payment.id).where(Payment.provider == p.provider, Payment.external_ref == ref, Payment.id != p.id)
        )
        if clash is not None:
            raise AppError("PAYMENT_REFERENCE_MISMATCH", "این شناسهٔ درگاه پیش‌تر به پرداخت دیگری متصل شده است.", 409)
        p.external_ref = ref
        p.meta = {
            **meta,
            "external_operation": "created",
            "reconciliation_required": False,
            "reconciled_by": str(actor_id),
            "instructions": {},
        }
        session.add(PaymentAttempt(payment_id=p.id, action="reconcile", result="bound", data={"external_ref": ref, "reason": reason}))
    elif action == "abandon":
        p.meta = {**meta, "external_operation": "create_abandoned", "reconciliation_required": False, "reconciled_by": str(actor_id)}
        session.add(PaymentAttempt(payment_id=p.id, action="reconcile", result="abandoned", data={"reason": reason}))
    else:
        raise AppError("PAYMENT_RECONCILE_ACTION", "عملیات نامعتبر است.", 400)
    audit.record(
        session,
        "payment.create_reconciled",
        actor_id=actor_id,
        actor_type="admin",
        entity_type="payment",
        entity_id=p.id,
        store_id=p.store_id,
        data={"action": action, "external_ref": p.external_ref if action == "bind" else None, "reason": reason},
    )
    await session.commit()
    if action == "abandon":
        return await mark_failed(session, p.id, actor_id=actor_id, reason=reason or "ایجاد پرداخت در درگاه تأیید نشد.")
    return p


async def handle_callback(session: AsyncSession, provider: str, params: dict) -> Payment:
    adapter = get_adapter(provider)
    pid = params.get("pid")
    try:
        payment_id = uuid.UUID(pid) if pid else None
    except (ValueError, AttributeError) as exc:
        raise AppError("PAYMENT_NOT_FOUND", "شناسه پرداخت نامعتبر است.", 404) from exc
    # NO row lock and NO open transaction across the gateway call (it can take up to 15 s and would pin a pooled connection):
    # read what is needed, release the connection, verify, then let ``mark_succeeded``/``mark_failed`` lock briefly. Both are
    # idempotent (status + ledger key), so a duplicate or racing callback is safe.
    p = await session.get(Payment, payment_id) if payment_id else None
    if not p or p.provider != provider:
        raise AppError("PAYMENT_NOT_FOUND", "پرداخت یافت نشد.", 404)
    pid_, status = p.id, p.status
    if status == P.SUCCEEDED:
        # The payment id is the only secret an unauthenticated duplicate callback needs: bound what it can make us store.
        seen = await session.scalar(
            select(func.count()).select_from(PaymentAttempt).where(PaymentAttempt.payment_id == pid_, PaymentAttempt.result == "duplicate")
        )
        if (seen or 0) < MAX_DUPLICATE_ATTEMPTS:
            session.add(PaymentAttempt(payment_id=pid_, action="callback", result="duplicate", data=bounded_callback_params(params)))
            await session.commit()
        return p
    store = await session.get(Store, p.store_id)
    if store is None:
        raise AppError("STORE_NOT_FOUND", "فروشگاه یافت نشد.", 404)
    cfg = await store_payment_settings(session, store, provider, require_enabled=False)
    session.expunge(p)  # keep a detached, fully-loaded copy for the adapter
    await (
        session.commit()
    )  # read-only: releases the pooled connection before the outbound HTTP call (expire_on_commit=False keeps objects usable)
    res = await adapter.verify_callback(params, p, settings=cfg)
    operation = (p.meta or {}).get("external_operation")
    if operation in ("creating", "create_unknown", "unknown") and not p.external_ref:
        # A callback authority alone is not enough to bind a lost create response to this payment:
        # another customer's same-amount authority could otherwise be replayed against this pid.
        # Even a positive provider verification is not sufficient without a trusted binding to this
        # payment ID. Keep it pending and retain the result for an authenticated reconciliation flow.
        session.add(
            PaymentAttempt(
                payment_id=pid_,
                action="callback",
                result="unmatched_unknown",
                data={"raw": res.raw, "provider_verification_succeeded": res.succeeded},
            )
        )
        await session.commit()
        return p
    if res.succeeded and res.external_ref:
        locked = await session.get(Payment, pid_, with_for_update=True, populate_existing=True)
        if locked is None:
            raise AppError("PAYMENT_NOT_FOUND", "پرداخت یافت نشد.", 404)
        if locked.external_ref and locked.external_ref != res.external_ref:
            raise AppError("PAYMENT_REFERENCE_MISMATCH", "شناسه پرداخت درگاه با رکورد پرداخت سازگار نیست.", 409)
        if not locked.external_ref:
            locked.external_ref = res.external_ref
    session.add(PaymentAttempt(payment_id=pid_, action="callback", result="ok" if res.succeeded else "failed", data=res.raw))
    await session.commit()
    return await (mark_succeeded(session, pid_) if res.succeeded else mark_failed(session, pid_, reason="پرداخت ناموفق بود."))


async def can_review(session: AsyncSession, user: User, payment: Payment) -> bool:
    """Admin, or the owner of the (reseller) store whose destination received the money."""
    if user.is_super_admin:
        return True
    store = await session.get(Store, payment.store_id)
    return bool(store and store.kind == "reseller" and store.owner_user_id == user.id)
