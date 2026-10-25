"""The store's own payment destination (gateway config) and review of manual-card payments."""

import json
import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from melorin.core import audit
from melorin.core.crypto import encrypt
from melorin.core.deps import OwnerCtx, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import StorePaymentConfiguration
from melorin.modules.payments import bank_sms, provisional, service as payments
from melorin.modules.payments.schemas import (
    BankSmsIgnoreIn,
    BankSmsLinkIn,
    BankSmsSourceIn,
    GraceResolveIn,
    GraceSettingsIn,
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
    from melorin.modules.payments.adapters.registry import get_adapter

    get_adapter(provider)
    row = await session.scalar(
        select(StorePaymentConfiguration).where(
            StorePaymentConfiguration.store_id == ctx.store.id, StorePaymentConfiguration.provider == provider
        )
    )
    if not row:
        row = StorePaymentConfiguration(store_id=ctx.store.id, provider=provider)
        session.add(row)
    row.is_enabled, row.public_config, row.updated_by = body.is_enabled, body.public_config, ctx.user.id
    if body.secret is not None:
        row.secret_enc = encrypt(json.dumps(body.secret))
    audit.record(
        session,
        "store.payment_config_updated",
        actor_id=ctx.user.id,
        actor_type="reseller",
        entity_type="store",
        entity_id=ctx.store.id,
        store_id=ctx.store.id,
        data={"provider": provider, "enabled": body.is_enabled, "secret_changed": body.secret is not None},
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
