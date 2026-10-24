import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events, flags, settings_store
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.core.crypto import decrypt
from melorin.domain.order_state import PaymentStatus
from melorin.kernel.models.identity import User
from melorin.modules.payments.adapters.registry import get_adapter
from melorin.modules.payments.gateway_catalog import validate_destination
from melorin.kernel.models.payments import Payment, PaymentAttempt
from melorin.kernel.models.stores import Store, StorePaymentConfiguration
from melorin.modules.wallet import service as wallet

P = PaymentStatus
log = logging.getLogger("melorin.payments")


_CURRENCY_CHECKED = frozenset({"zarinpal", "external_gateway", "crypto", "telegram_stars"})


def _check_currency(provider: str, currency: str) -> None:
    if provider not in _CURRENCY_CHECKED:
        return
    try:
        validate_destination(provider, currency)
    except ValueError as exc:
        raise AppError("PAYMENT_CURRENCY_UNSUPPORTED", "این درگاه با ارز فروشگاه سازگار نیست.", 400) from exc


def _store_configured_settings(cfg: StorePaymentConfiguration, provider: str) -> dict:
    """Settings from the store's own configuration row; raises when it is disabled or its destination is incomplete."""
    if not cfg.is_enabled:
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
        f"destination.{provider}": {**public, **secret},
        "limits": public,
    }


async def _main_store_legacy_settings(session: AsyncSession, provider: str) -> dict:
    """The main store may still use the legacy global settings; its destination must be complete."""
    legacy = await settings_store.all_settings(session)
    if provider == "manual_card" and not all((legacy.get("card.info") or {}).get(k) for k in ("card_number", "holder")):
        raise AppError("PAYMENT_DESTINATION_MISSING", "مقصد پرداخت کارت‌به‌کارت فروشگاه اصلی کامل نیست.", 409)
    if provider == "zarinpal" and not (legacy.get(f"gateway.{provider}") or {}).get("merchant_id"):
        raise AppError("PAYMENT_DESTINATION_MISSING", "مقصد پرداخت درگاه فروشگاه اصلی پیکربندی نشده است.", 409)
    return {**legacy, "limits": {}}


async def store_payment_settings(session: AsyncSession, store: Store, provider: str) -> dict:
    """Payment destination belongs to the Store (v1.1). Main store may fall back to legacy global settings."""
    cfg = await session.scalar(
        select(StorePaymentConfiguration).where(
            StorePaymentConfiguration.store_id == store.id, StorePaymentConfiguration.provider == provider
        )
    )
    _check_currency(provider, store.currency)
    if cfg is not None:
        return _store_configured_settings(cfg, provider)
    if store.kind == "main":
        return await _main_store_legacy_settings(session, provider)
    raise AppError("PAYMENT_METHOD_DISABLED", "روش شارژ برای این فروشگاه پیکربندی نشده است.", 400)


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
    """Wallet top-up of THIS store only. Money goes to this store's own destination; never to another store."""
    existing = await session.scalar(
        select(Payment).where(Payment.user_id == user.id, Payment.store_id == store.id, Payment.idempotency_key == idempotency_key)
    )
    if existing:
        if existing.amount != amount or existing.provider != provider or existing.purpose != purpose:
            raise AppError("IDEMPOTENCY_KEY_REUSE", "کلید idempotency با درخواست دیگری استفاده شده است.", 409)
        return existing, (existing.meta or {}).get("instructions", {})
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
        meta={},
    )
    session.add(p)
    try:
        await session.flush()
        await session.commit()  # persist before the external call
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(Payment).where(Payment.user_id == user.id, Payment.store_id == store.id, Payment.idempotency_key == idempotency_key)
        )
        if existing:
            return existing, (existing.meta or {}).get("instructions", {})
        raise
    try:
        res = await adapter.create_payment_intent(
            p, callback_url=f"{callback_base}/api/v1/payments/callbacks/{provider}?pid={p.id}", settings=cfg
        )
    except Exception as exc:
        log.warning("payment create failed payment=%s provider=%s", p.id, p.provider, exc_info=True)
        p.meta = {"external_operation": "create_failed", "error": str(exc)[:300]}
        session.add(PaymentAttempt(payment_id=p.id, action="create", result="failed", data={"error": str(exc)[:500]}))
        await session.commit()
        raise
    p.external_ref = res.external_ref
    p.meta = {"external_operation": "created", "instructions": res.instructions}
    session.add(PaymentAttempt(payment_id=p.id, action="create", result="ok", data={"external_ref": res.external_ref}))
    await session.commit()
    return p, res.instructions


async def attach_receipt(session: AsyncSession, payment: Payment, file_id: uuid.UUID, claim: dict | None = None) -> None:
    """``claim`` = what the customer read off the receipt (time, reference, source card tail); used by bank-SMS matching."""
    if payment.provider != "manual_card" or payment.status not in (P.PENDING, P.AWAITING_REVIEW):
        raise AppError("INVALID_PAYMENT_STATE", "برای این پرداخت امکان ارسال رسید نیست.", 409)
    payment.receipt_file_id = file_id
    if claim:
        payment.meta = {**(payment.meta or {}), "receipt_claim": claim}
    payment.status = P.AWAITING_REVIEW
    await events.emit(
        session,
        events.EVENT_CENTER,
        {
            "store_id": payment.store_id,
            "topic": "payments",
            "text": f"🧾 رسید جدید برای بررسی\nمبلغ: {payment.amount:,}\nشناسه: {payment.id}",
        },
    )
    await session.commit()


async def mark_succeeded(session: AsyncSession, payment_id: uuid.UUID, *, actor_id=None, actor_type="system", note=None) -> Payment:
    """Idempotent: duplicate callbacks/approvals never double-credit (row lock + ledger idempotency key)."""
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if p.status == P.SUCCEEDED:
        return p
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
    await events.emit(
        session,
        events.NOTIFY,
        {
            "user_id": p.user_id,
            "store_id": p.store_id,
            "kind": "payment",
            "title": "پرداخت تأیید شد",
            "body": f"پرداخت {p.amount:,} تأیید شد.",
        },
        dedup_key=f"notify:payment:{p.id}",
    )
    await session.commit()
    return p


async def mark_failed(session: AsyncSession, payment_id: uuid.UUID, *, actor_id=None, reason=None) -> Payment:
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if p.status in (P.SUCCEEDED, P.FAILED):
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
    await events.emit(
        session,
        events.NOTIFY,
        {
            "user_id": p.user_id,
            "store_id": p.store_id,
            "kind": "payment",
            "title": "پرداخت ناموفق",
            "body": reason or "پرداخت شما تأیید نشد.",
        },
    )
    await session.commit()
    return p


async def refund_payment(session: AsyncSession, payment_id: uuid.UUID, *, actor_id, reason: str | None = None) -> Payment:
    """Refund the external payment, then reverse its wallet credit once."""
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if not p:
        raise AppError("PAYMENT_NOT_FOUND", "پرداخت یافت نشد.", 404)
    if p.status == P.REFUNDED:
        return p
    if p.status != P.SUCCEEDED:
        raise AppError("INVALID_PAYMENT_STATE", "فقط پرداخت موفق قابل استرداد است.", 409)
    store = await session.get(Store, p.store_id)
    cfg = await store_payment_settings(session, store, p.provider)
    p.meta = {**(p.meta or {}), "refund_operation": "pending"}
    await session.flush()
    try:
        result = await get_adapter(p.provider).refund(p, settings=cfg)
    except Exception as exc:
        log.warning("payment refund failed payment=%s provider=%s", p.id, p.provider, exc_info=True)
        p.meta = {**(p.meta or {}), "refund_operation": "failed", "refund_error": str(exc)[:300]}
        session.add(PaymentAttempt(payment_id=p.id, action="refund", result="failed", data={"error": str(exc)[:500]}))
        await session.commit()
        raise
    tx = await wallet.find_tx(session, f"payment:{p.id}")
    if tx:
        await wallet.reverse(
            session, tx, key=f"payment:{p.id}:refund", kind="topup_refund", actor_id=actor_id, memo=reason or "استرداد شارژ"
        )
    p.status = P.REFUNDED
    p.meta = {**(p.meta or {}), "refund_operation": "succeeded", "refund_external_ref": result.external_ref}
    session.add(PaymentAttempt(payment_id=p.id, action="refund", result="ok", data=result.raw))
    audit.record(
        session,
        "payment.refunded",
        actor_id=actor_id,
        actor_type="admin",
        entity_type="payment",
        entity_id=p.id,
        store_id=p.store_id,
        data={"reason": reason, "external_ref": result.external_ref},
    )
    await session.commit()
    return p


async def handle_callback(session: AsyncSession, provider: str, params: dict) -> Payment:
    adapter = get_adapter(provider)
    pid = params.get("pid")
    try:
        payment_id = uuid.UUID(pid) if pid else None
    except (ValueError, AttributeError) as exc:
        raise AppError("PAYMENT_NOT_FOUND", "شناسه پرداخت نامعتبر است.", 404) from exc
    p = await session.get(Payment, payment_id, with_for_update=True) if payment_id else None
    if not p or p.provider != provider:
        raise AppError("PAYMENT_NOT_FOUND", "پرداخت یافت نشد.", 404)
    if p.status == P.SUCCEEDED:
        session.add(PaymentAttempt(payment_id=p.id, action="callback", result="duplicate", data=params))
        await session.commit()
        return p
    store = await session.get(Store, p.store_id)
    cfg = await store_payment_settings(session, store, provider)
    res = await adapter.verify_callback(params, p, settings=cfg)
    session.add(PaymentAttempt(payment_id=p.id, action="callback", result="ok" if res.succeeded else "failed", data=res.raw))
    await session.commit()
    return await (mark_succeeded(session, p.id) if res.succeeded else mark_failed(session, p.id, reason="پرداخت ناموفق بود."))


async def can_review(session: AsyncSession, user: User, payment: Payment) -> bool:
    """Admin, or the owner of the (reseller) store whose destination received the money."""
    if user.is_super_admin:
        return True
    store = await session.get(Store, payment.store_id)
    return bool(store and store.kind == "reseller" and store.owner_user_id == user.id)
