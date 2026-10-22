"""The store's own payment destination (gateway config) and review of manual-card payments."""

import json
import uuid

from fastapi import APIRouter
from sqlalchemy import select

from melorin.core import audit
from melorin.core.crypto import encrypt
from melorin.core.deps import OwnerCtx, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import StorePaymentConfiguration
from melorin.modules.payments import service as payments
from melorin.modules.payments.schemas import payment_out
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
    if body.approve:
        p = await payments.mark_succeeded(session, p.id, actor_id=ctx.user.id, actor_type="reseller", note=body.note)
    else:
        p = await payments.mark_failed(session, p.id, actor_id=ctx.user.id, reason=body.note)
    return payment_out(p)
