import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from melorin.core.config import get_settings
from melorin.core.deps import Session, StoreCtx
from melorin.core.errors import AppError
from melorin.core.scope import StoreScope
from melorin.core.storage import get_storage, validate_upload
from melorin.core.ratelimit import RateLimit
from melorin.modules.payments import bank_sms, service
from melorin.kernel.models.payments import Payment
from melorin.modules.payments.schemas import PaymentOut, TopupRequest, payment_out
from melorin.kernel.models.system import FileObject

router = APIRouter(tags=["payments"])
log = logging.getLogger("melorin.payments")


@router.post("/stores/{store_id}/wallet/topups", response_model=PaymentOut)
async def topup(
    body: TopupRequest,
    ctx: StoreCtx,
    session: Session,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=100),
):
    p, _ = await service.create_intent(
        session,
        user=ctx.user,
        store=ctx.store,
        purpose="wallet_topup",
        amount=body.amount,
        provider=body.provider,
        idempotency_key=idempotency_key,
        callback_base=get_settings().public_api_url.rstrip("/"),
    )
    return payment_out(p)


@router.get("/stores/{store_id}/payments", response_model=list[PaymentOut])
async def my_payments(ctx: StoreCtx, session: Session):
    """Only the caller's own payments / top-ups of THIS store."""
    rows = (
        await session.scalars(select(Payment).where(*StoreScope.of(ctx).where(Payment)).order_by(Payment.created_at.desc()).limit(100))
    ).all()
    return [payment_out(p) for p in rows]


@router.get("/stores/{store_id}/payments/{payment_id}", response_model=PaymentOut)
async def get_payment(payment_id: uuid.UUID, ctx: StoreCtx, session: Session):
    return payment_out(await StoreScope.of(ctx).get(session, Payment, payment_id, "پرداخت"))


@router.post("/stores/{store_id}/payments/{payment_id}/receipt", response_model=PaymentOut)
async def upload_receipt(
    payment_id: uuid.UUID,
    ctx: StoreCtx,
    session: Session,
    file: UploadFile = File(...),
    paid_at: str | None = Form(default=None, max_length=40),
    reference: str | None = Form(default=None, max_length=40),
    source_card_last4: str | None = Form(default=None, max_length=8),
):
    """Receipt image + the facts printed on it. With bank-SMS auto verification the SMS (not the image) is the proof."""
    user = ctx.user
    p = await StoreScope.of(ctx).get(session, Payment, payment_id, "پرداخت")
    claim = bank_sms.parse_claim(paid_at, reference, source_card_last4)
    limit = get_settings().max_upload_bytes
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise AppError("FILE_TOO_LARGE", "حجم فایل زیاد است.", 413)
    data = bytes(data)
    digest = validate_upload(data, file.content_type or "")
    key = await get_storage().put(data, file.content_type)
    fo = FileObject(
        owner_user_id=user.id,
        store_id=p.store_id,
        purpose="receipt",
        storage_key=key,
        content_type=file.content_type,
        size=len(data),
        sha256=digest,
    )
    session.add(fo)
    await session.flush()
    await service.attach_receipt(session, p, fo.id, claim)
    await bank_sms.try_auto_verify_payment(session, p)
    await session.refresh(p)
    return payment_out(p)


_SMS_TEXT_KEYS = ("text", "message", "body", "msg", "content", "sms")
_SMS_SENDER_KEYS = ("sender", "from", "address", "number", "originating_address")


def _first(data: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = data.get(k)
        if isinstance(v, (str, int)) and str(v).strip():
            return str(v)
    return None


@router.post("/payments/bank-sms/{store_id}", operation_id="bank_sms_webhook", dependencies=[Depends(RateLimit("bank_sms", 120, 60))])
async def bank_sms_webhook(
    store_id: uuid.UUID,
    request: Request,
    session: Session,
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    authorization: str | None = Header(default=None),
):
    """Endpoint for an SMS-forwarder app on the store owner's phone. JSON or form body with ``text`` (+ ``sender``)."""
    token = x_webhook_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    src = await bank_sms.authenticate(session, store_id, token)
    raw = await request.body()
    if len(raw) > 8192:
        raise AppError("BANK_SMS_TOO_LONG", "درخواست بیش از حد بزرگ است.", 413)
    data: dict = {}
    ctype = (request.headers.get("content-type") or "").lower()
    try:
        if "json" in ctype:
            import json as _json

            parsed = _json.loads(raw.decode("utf-8") or "{}")
            data = parsed if isinstance(parsed, dict) else {}
        else:
            from urllib.parse import parse_qsl

            data = dict(parse_qsl(raw.decode("utf-8"), keep_blank_values=True))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("BANK_SMS_BAD_BODY", "بدنه‌ی درخواست نامعتبر است.", 400) from exc
    text = _first(data, _SMS_TEXT_KEYS)
    if text is None:
        raise AppError("BANK_SMS_EMPTY", "متن پیامک خالی است.", 422)
    m, created = await bank_sms.ingest(session, src, text, sender=_first(data, _SMS_SENDER_KEYS))
    return {"ok": True, "status": m.status, "duplicate": not created}


async def _handle_payment_callback(provider: str, request: Request, session: Session):
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            params.update(dict(await request.form()))
        except Exception:
            # A gateway may POST an empty or non-form body; the query string still carries the callback fields.
            # Never log the body: it can contain payment authority/token values.
            log.warning("payment callback body is not a parsable form provider=%s", provider)
    p = await service.handle_callback(session, provider, params)
    return RedirectResponse(f"{get_settings().store_web_url}/account/payments/{p.id}?status={p.status}", status_code=303)


# One route per method with an explicit operation_id: a single api_route(methods=[GET, POST]) produced the same
# OpenAPI operationId twice, which breaks client generators.
@router.get("/payments/callbacks/{provider}", operation_id="payment_callback_get")
async def payment_callback_get(provider: str, request: Request, session: Session):
    return await _handle_payment_callback(provider, request, session)


@router.post("/payments/callbacks/{provider}", operation_id="payment_callback_post")
async def payment_callback_post(provider: str, request: Request, session: Session):
    return await _handle_payment_callback(provider, request, session)
