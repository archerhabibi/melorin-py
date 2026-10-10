import uuid

from fastapi import APIRouter, File, Header, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from melorin.core.config import get_settings
from melorin.core.deps import CurrentUser, Session, StoreCtx
from melorin.core.errors import AppError, NotFound
from melorin.core.storage import get_storage, validate_upload
from melorin.modules.payments import service
from melorin.modules.payments.models import Payment
from melorin.modules.payments.schemas import PaymentOut, TopupRequest, payment_out
from melorin.modules.system.models import FileObject

router = APIRouter(tags=["payments"])


@router.post("/stores/{store_id}/wallet/topups", response_model=PaymentOut)
async def topup(body: TopupRequest, ctx: StoreCtx, session: Session, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=100)):
    p, _ = await service.create_intent(session, user=ctx.user, store=ctx.store, purpose="wallet_topup", amount=body.amount, provider=body.provider, idempotency_key=idempotency_key, callback_base=get_settings().public_api_url.rstrip("/"))
    return payment_out(p)


@router.get("/payments", response_model=list[PaymentOut])
async def my_payments(user: CurrentUser, session: Session):
    rows = (await session.scalars(select(Payment).where(Payment.user_id == user.id).order_by(Payment.created_at.desc()).limit(100))).all()
    return [payment_out(p) for p in rows]


@router.get("/payments/{payment_id}", response_model=PaymentOut)
async def get_payment(payment_id: uuid.UUID, user: CurrentUser, session: Session):
    p = await session.get(Payment, payment_id)
    if not p or (p.user_id != user.id and not user.is_super_admin):
        raise NotFound("پرداخت")
    return payment_out(p)


@router.post("/payments/{payment_id}/receipt", response_model=PaymentOut)
async def upload_receipt(payment_id: uuid.UUID, user: CurrentUser, session: Session, file: UploadFile = File(...)):
    p = await session.get(Payment, payment_id)
    if not p or p.user_id != user.id:
        raise NotFound("پرداخت")
    limit = get_settings().max_upload_bytes
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise AppError("FILE_TOO_LARGE", "حجم فایل زیاد است.", 413)
    data = bytes(data)
    digest = validate_upload(data, file.content_type or "")
    key = await get_storage().put(data, file.content_type)
    fo = FileObject(owner_user_id=user.id, store_id=p.store_id, purpose="receipt", storage_key=key, content_type=file.content_type, size=len(data), sha256=digest)
    session.add(fo)
    await session.flush()
    await service.attach_receipt(session, p, fo.id)
    return payment_out(p)


@router.api_route("/payments/callbacks/{provider}", methods=["GET", "POST"])
async def payment_callback(provider: str, request: Request, session: Session):
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            params.update(dict(await request.form()))
        except Exception:
            pass
    p = await service.handle_callback(session, provider, params)
    return RedirectResponse(f"{get_settings().store_web_url}/account/payments/{p.id}?status={p.status}", status_code=303)
