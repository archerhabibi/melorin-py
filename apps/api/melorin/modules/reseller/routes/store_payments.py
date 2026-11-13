"""The store's own payment destination (gateway config) and review of manual-card payments."""

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from melorin.core.deps import OwnerCtx, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import StorePaymentConfiguration
from melorin.modules.payments import store_config, bank_sms, provisional, receipt_fingerprints, service as payments
from melorin.modules.payments.schemas import (
    BankSmsIgnoreIn,
    BankSmsLinkIn,
    BankSmsSourceIn,
    GraceResolveIn,
    GraceSettingsIn,
    ReceiptDupSettingsIn,
    payment_out,
)
from melorin.modules.reseller.schemas import (
    PaymentConfigIn,
    PaymentReview,
)

router = APIRouter(tags=["reseller"])


@router.get("/stores/{store_id}/reseller/payment-config")
async def get_payment_config(ctx: OwnerCtx, session: Session):
    rows = (await session.scalars(select(StorePaymentConfiguration).where(StorePaymentConfiguration.store_id == ctx.store.id))).all()
    return [
        {"provider": r.provider, "is_enabled": r.is_enabled, "public_config": r.public_config, "has_secret": bool(r.secret_enc)}
        for r in rows
    ]


@router.put("/stores/{store_id}/reseller/payment-config/{provider}")
async def put_payment_config(provider: str, body: PaymentConfigIn, ctx: OwnerCtx, session: Session):
    await store_config.upsert(
        session,
        store_id=ctx.store.id,
        provider=provider,
        is_enabled=body.is_enabled,
        public_config=body.public_config,
        secret=body.secret,
        actor_id=ctx.user.id,
        actor_type="reseller",
    )
    await session.commit()
    return {"ok": True}


@router.get("/stores/{store_id}/reseller/payments")
async def store_payments(ctx: OwnerCtx, session: Session, status: str | None = None):
    q = select(Payment).where(Payment.store_id == ctx.store.id).order_by(Payment.created_at.desc()).limit(200)
    if status:
        q = q.where(Payment.status == status)
    return [payment_out(p) for p in (await session.scalars(q)).all()]


@router.post("/stores/{store_id}/reseller/payments/{payment_id}/review")
async def review_store_payment(payment_id: uuid.UUID, body: PaymentReview, ctx: OwnerCtx, session: Session):
    p = await session.get(Payment, payment_id)
    if not p or p.store_id != ctx.store.id:
        raise NotFound("پرداخت")
    if p.provider != "manual_card":
        raise AppError("PAYMENT_REVIEW_FORBIDDEN", "تأیید پرداخت‌های درگاه فقط پس از callback معتبر انجام می‌شود.", 403)
    if provisional.state(p):
        p = await provisional.resolve(
            session, ctx.store.id, p.id, approve=body.approve, actor_id=ctx.user.id, actor_type="reseller", note=body.note
        )
        return payment_out(p)
    if body.approve:
        p = await payments.mark_succeeded(session, p.id, actor_id=ctx.user.id, actor_type="reseller", note=body.note)
    else:
        p = await payments.mark_failed(session, p.id, actor_id=ctx.user.id, reason=body.note)
    return payment_out(p)


# ----- Card-to-card auto verification (bank SMS) for the reseller's own store -----
@router.get("/stores/{store_id}/reseller/bank-sms")
async def reseller_bank_sms_overview(ctx: OwnerCtx, session: Session, status: str | None = Query(default=None)):
    src = await bank_sms.get_source(session, ctx.store.id)
    return {
        "source": bank_sms.source_out(src, store_id=ctx.store.id),
        "messages": [bank_sms.message_out(m) for m in await bank_sms.list_messages(session, ctx.store.id, status=status)],
    }


@router.put("/stores/{store_id}/reseller/bank-sms/source")
async def reseller_bank_sms_save_source(body: BankSmsSourceIn, ctx: OwnerCtx, session: Session):
    src, token = await bank_sms.save_source(
        session, ctx.store, actor_id=ctx.user.id, actor_type="reseller", **body.model_dump(exclude_unset=True)
    )
    return {"source": bank_sms.source_out(src), "token": token}


@router.post("/stores/{store_id}/reseller/bank-sms/token")
async def reseller_bank_sms_rotate_token(ctx: OwnerCtx, session: Session):
    return {"token": await bank_sms.rotate_token(session, ctx.store, actor_id=ctx.user.id, actor_type="reseller")}


@router.post("/stores/{store_id}/reseller/bank-sms/reconcile")
async def reseller_bank_sms_reconcile(ctx: OwnerCtx, session: Session):
    return await bank_sms.reconcile_store(session, ctx.store)


@router.post("/stores/{store_id}/reseller/bank-sms/{sms_id}/link")
async def reseller_bank_sms_link(sms_id: uuid.UUID, body: BankSmsLinkIn, ctx: OwnerCtx, session: Session):
    m = await bank_sms.manual_link(session, ctx.store, sms_id, body.payment_id, actor_id=ctx.user.id, actor_type="reseller")
    return bank_sms.message_out(m)


@router.post("/stores/{store_id}/reseller/bank-sms/{sms_id}/ignore")
async def reseller_bank_sms_ignore(sms_id: uuid.UUID, body: BankSmsIgnoreIn, ctx: OwnerCtx, session: Session):
    m = await bank_sms.set_ignored(session, ctx.store, sms_id, ignored=body.ignored, actor_id=ctx.user.id, actor_type="reseller")
    return bank_sms.message_out(m)


# ----- Time-boxed manual review for the reseller's own store -----
@router.get("/stores/{store_id}/reseller/receipt-review")
async def reseller_receipt_review_queue(ctx: OwnerCtx, session: Session):
    return await provisional.queue(session, ctx.store.id)


@router.put("/stores/{store_id}/reseller/receipt-review/settings")
async def reseller_receipt_review_settings(body: GraceSettingsIn, ctx: OwnerCtx, session: Session):
    return await provisional.save_config(
        session, ctx.store, body.model_dump(exclude_unset=True), actor_id=ctx.user.id, actor_type="reseller"
    )


@router.post("/stores/{store_id}/reseller/receipt-review/{payment_id}")
async def reseller_receipt_review_resolve(payment_id: uuid.UUID, body: GraceResolveIn, ctx: OwnerCtx, session: Session):
    p = await provisional.resolve(
        session, ctx.store.id, payment_id, approve=body.approve, actor_id=ctx.user.id, actor_type="reseller", note=body.note
    )
    return {"ok": True, "status": p.status, "provisional": provisional.state(p)}


# ----- Duplicate receipt pictures (the reseller's own store) -----
@router.get("/stores/{store_id}/reseller/receipt-duplicates/settings")
async def reseller_receipt_dup_settings(ctx: OwnerCtx, session: Session):
    return {"policy": await receipt_fingerprints.get_policy(session, ctx.store.id)}


@router.put("/stores/{store_id}/reseller/receipt-duplicates/settings")
async def reseller_receipt_dup_save_settings(body: ReceiptDupSettingsIn, ctx: OwnerCtx, session: Session):
    return await receipt_fingerprints.save_policy(session, ctx.store, body.policy, actor_id=ctx.user.id, actor_type="reseller")


@router.get("/stores/{store_id}/reseller/payments/{payment_id}/receipt-duplicates")
async def reseller_payment_receipt_duplicates(payment_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    """Own-store payments that share this picture; payments of other stores are only counted, never named."""
    p = await session.get(Payment, payment_id)
    if not p or p.store_id != ctx.store.id:
        raise NotFound("پرداخت")
    matches = await receipt_fingerprints.matches_for_payment(session, payment_id)
    return {
        "payment_id": payment_id,
        "duplicates": [
            {"payment_id": m.payment_id, "status": m.status, "matched_by": list(m.by)} for m in matches if m.store_id == ctx.store.id
        ],
        "other_stores": sum(1 for m in matches if m.store_id != ctx.store.id),
    }
