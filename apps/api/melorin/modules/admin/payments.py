"""Admin API - payments routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import select
from melorin.core import audit
from melorin.core.deps import AdminUser, Session, main_store
from melorin.core.errors import NotFound
from melorin.kernel.models.stores import Store
from melorin.modules.payments import store_config, bank_sms, provisional, receipt_fingerprints, service as payment_service
from melorin.modules.payments.schemas import (
    BankSmsIgnoreIn,
    BankSmsLinkIn,
    BankSmsSourceIn,
    GraceResolveIn,
    GraceSettingsIn,
    ReceiptDupSettingsIn,
)
from melorin.kernel.models.payments import Payment
from melorin.modules.reseller.schemas import PaymentConfigIn
from melorin.modules.admin.schemas import (
    OrderAction,
    ReviewPayment,
)

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


# ----- Main store payment destination (the same per-store model resellers use) -----
@router.get("/payment-destinations")
async def payment_destinations(_: AdminUser, session: Session):
    store = await main_store(session)
    return [store_config.admin_view(r) for r in await store_config.list_configs(session, store.id)]


@router.put("/payment-destinations/{provider}")
async def put_payment_destination(provider: str, body: PaymentConfigIn, admin: AdminUser, session: Session):
    store_config.require_main_store_provider(provider)
    store = await main_store(session)
    await store_config.upsert(
        session,
        store_id=store.id,
        provider=provider,
        is_enabled=body.is_enabled,
        public_config=body.public_config,
        secret=body.secret,
        actor_id=admin.id,
        actor_type="admin",
    )
    await session.commit()
    return {"ok": True}


# ----- Payments, orders, manual recovery -----
@router.get("/payments", response_model=list[dict])
async def payments(_: AdminUser, session: Session, status: str | None = Query(default=None)):
    q = select(Payment).order_by(Payment.created_at.desc()).limit(200)
    if status:
        q = q.where(Payment.status == status)
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "store_id": p.store_id,
            "amount": p.amount,
            "currency": p.currency,
            "provider": p.provider,
            "status": p.status,
            "has_receipt": bool(p.receipt_file_id),
            "receipt_duplicate": bool((p.meta or {}).get("receipt_duplicate")),
            "created_at": p.created_at,
        }
        for p in (await session.scalars(q)).all()
    ]


@router.get("/payments/{payment_id}/receipt")
async def payment_receipt(payment_id: uuid.UUID, admin: AdminUser, session: Session):
    """Admin-only receipt download. Files stay private; every view is audited."""
    from melorin.core.storage import get_storage
    from melorin.kernel.models.system import FileObject

    p = await session.get(Payment, payment_id)
    if not p or not p.receipt_file_id:
        raise NotFound("رسید")
    fo = await session.get(FileObject, p.receipt_file_id)
    if not fo:
        raise NotFound("رسید")
    data = await get_storage().get(fo.storage_key)
    audit.record(session, "payment.receipt_viewed", actor_id=admin.id, actor_type="admin", entity_type="payment", entity_id=p.id)
    await session.commit()
    return Response(
        content=data,
        media_type=fo.content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"},
    )


@router.get("/payments/{payment_id}/receipt-duplicates")
async def payment_receipt_duplicates(payment_id: uuid.UUID, _: AdminUser, session: Session):
    """Every other payment (any store) whose receipt picture has the same fingerprint, with how it matched."""
    if not await session.get(Payment, payment_id):
        raise NotFound("پرداخت")
    matches = await receipt_fingerprints.matches_for_payment(session, payment_id)
    return {
        "payment_id": payment_id,
        "duplicates": [{"payment_id": m.payment_id, "store_id": m.store_id, "status": m.status, "matched_by": list(m.by)} for m in matches],
    }


@router.post("/payments/{payment_id}/review")
async def review_payment(payment_id: uuid.UUID, body: ReviewPayment, admin: AdminUser, session: Session):
    p = await session.get(Payment, payment_id)
    if not p:
        raise NotFound("پرداخت")
    if provisional.state(p):  # a provisional credit: confirm keeps it, reject reverses it through the ledger
        await provisional.resolve(session, p.store_id, p.id, approve=body.approve, actor_id=admin.id, actor_type="admin", note=body.reason)
        await session.refresh(p)
        return {"ok": True, "status": p.status}
    if body.approve:
        await payment_service.mark_succeeded(session, p.id, actor_id=admin.id, actor_type="admin", note=body.reason)
    else:
        await payment_service.mark_failed(session, p.id, actor_id=admin.id, reason=body.reason)
    audit.record(
        session,
        "payment.reviewed",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="payment",
        entity_id=p.id,
        data={"approve": body.approve, "reason": body.reason},
    )
    await session.commit()
    return {"ok": True, "status": p.status}


@router.post("/payments/{payment_id}/refund")
async def refund_payment(payment_id: uuid.UUID, body: OrderAction, admin: AdminUser, session: Session):
    p = await payment_service.refund_payment(session, payment_id, actor_id=admin.id, reason=body.reason)
    return {"ok": True, "status": p.status, "payment_id": p.id}


# ----- Card-to-card auto verification (bank SMS) -----
async def _store(session, store_id: uuid.UUID) -> Store:
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    return store


@router.get("/stores/{store_id}/bank-sms")
async def bank_sms_overview(store_id: uuid.UUID, _: AdminUser, session: Session, status: str | None = Query(default=None)):
    store = await _store(session, store_id)
    src = await bank_sms.get_source(session, store.id)
    return {
        "source": bank_sms.source_out(src, store_id=store.id),
        "messages": [bank_sms.message_out(m) for m in await bank_sms.list_messages(session, store.id, status=status)],
    }


@router.put("/stores/{store_id}/bank-sms/source")
async def bank_sms_save_source(store_id: uuid.UUID, body: BankSmsSourceIn, admin: AdminUser, session: Session):
    store = await _store(session, store_id)
    src, token = await bank_sms.save_source(session, store, actor_id=admin.id, actor_type="admin", **body.model_dump(exclude_unset=True))
    return {"source": bank_sms.source_out(src), "token": token}


@router.post("/stores/{store_id}/bank-sms/token")
async def bank_sms_rotate_token(store_id: uuid.UUID, admin: AdminUser, session: Session):
    store = await _store(session, store_id)
    return {"token": await bank_sms.rotate_token(session, store, actor_id=admin.id, actor_type="admin")}


@router.post("/stores/{store_id}/bank-sms/reconcile")
async def bank_sms_reconcile(store_id: uuid.UUID, _: AdminUser, session: Session):
    return await bank_sms.reconcile_store(session, await _store(session, store_id))


@router.post("/stores/{store_id}/bank-sms/{sms_id}/link")
async def bank_sms_link(store_id: uuid.UUID, sms_id: uuid.UUID, body: BankSmsLinkIn, admin: AdminUser, session: Session):
    store = await _store(session, store_id)
    m = await bank_sms.manual_link(session, store, sms_id, body.payment_id, actor_id=admin.id, actor_type="admin")
    return bank_sms.message_out(m)


@router.post("/stores/{store_id}/bank-sms/{sms_id}/ignore")
async def bank_sms_ignore(store_id: uuid.UUID, sms_id: uuid.UUID, body: BankSmsIgnoreIn, admin: AdminUser, session: Session):
    store = await _store(session, store_id)
    m = await bank_sms.set_ignored(session, store, sms_id, ignored=body.ignored, actor_id=admin.id, actor_type="admin")
    return bank_sms.message_out(m)


# ----- Time-boxed manual review (provisional approval after N minutes) -----
@router.get("/stores/{store_id}/receipt-review")
async def receipt_review_queue(store_id: uuid.UUID, _: AdminUser, session: Session):
    store = await _store(session, store_id)
    return await provisional.queue(session, store.id)


@router.put("/stores/{store_id}/receipt-review/settings")
async def receipt_review_settings(store_id: uuid.UUID, body: GraceSettingsIn, admin: AdminUser, session: Session):
    store = await _store(session, store_id)
    return await provisional.save_config(session, store, body.model_dump(exclude_unset=True), actor_id=admin.id, actor_type="admin")


@router.post("/stores/{store_id}/receipt-review/{payment_id}")
async def receipt_review_resolve(store_id: uuid.UUID, payment_id: uuid.UUID, body: GraceResolveIn, admin: AdminUser, session: Session):
    store = await _store(session, store_id)
    p = await provisional.resolve(
        session, store.id, payment_id, approve=body.approve, actor_id=admin.id, actor_type="admin", note=body.note
    )
    return {"ok": True, "status": p.status, "provisional": provisional.state(p)}


# ----- Duplicate receipt pictures -----
@router.get("/stores/{store_id}/receipt-duplicates/settings")
async def receipt_dup_settings(store_id: uuid.UUID, _: AdminUser, session: Session):
    store = await _store(session, store_id)
    return {"policy": await receipt_fingerprints.get_policy(session, store.id)}


@router.put("/stores/{store_id}/receipt-duplicates/settings")
async def receipt_dup_save_settings(store_id: uuid.UUID, body: ReceiptDupSettingsIn, admin: AdminUser, session: Session):
    store = await _store(session, store_id)
    return await receipt_fingerprints.save_policy(session, store, body.policy, actor_id=admin.id, actor_type="admin")
