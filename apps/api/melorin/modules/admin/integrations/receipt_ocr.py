"""Automatic receipt reading (OCR): engine choice, vision API key, model and a live connection test."""

import base64
import re
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter

from melorin.core import integrations
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError
from melorin.modules.admin.integrations._audit import record_integration
from melorin.modules.admin.integrations.schemas import ReceiptOcrIn
from melorin.modules.payments import receipt_ocr

router = APIRouter(prefix="/integrations", tags=["admin-integrations"])
LANG_RE = re.compile(r"^[a-z]{3}(_[a-z]+)?(\+[a-z]{3}(_[a-z]+)?){0,3}$")
# 1x1 white PNG: enough to prove the key, model and network path work without sending any customer data.
_PROBE_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def receipt_ocr_public(cfg: dict) -> dict:
    """Public view + what would really run right now (``active_engine``) so the UI never has to guess."""
    resolved = receipt_ocr.resolve(cfg)
    return {
        **integrations.public_receipt_ocr(cfg),
        "active_engine": receipt_ocr.configured_engine(resolved),
        "tesseract_available": receipt_ocr.tesseract_available(),
    }


@router.put("/receipt-ocr")
async def update_receipt_ocr(body: ReceiptOcrIn, admin: AdminUser, session: Session):
    engine = body.engine.strip().lower()
    if engine not in integrations.RECEIPT_OCR_ENGINES:
        raise AppError("OCR_ENGINE_INVALID", "موتور خواندن رسید نامعتبر است.", 400)
    base = body.base_url.strip().rstrip("/")
    if urlparse(base).scheme != "https" or not urlparse(base).netloc:
        raise AppError("OCR_BASE_URL_INVALID", "آدرس سرویس باید با https شروع شود.", 400)
    lang = body.tesseract_lang.strip().lower()
    if not LANG_RE.match(lang):
        raise AppError("OCR_LANG_INVALID", "زبان tesseract نامعتبر است؛ نمونه: fas+eng", 400)
    current = await integrations.get_receipt_ocr(session)
    key_enc = integrations.merge_secret(current.get("api_key_enc"), body.api_key.strip() if body.api_key is not None else None)
    if engine == "vision" and not key_enc:
        raise AppError("OCR_KEY_REQUIRED", "برای موتور «بینایی» کلید API لازم است.", 400)
    new = {
        "engine": engine,
        "api_key_enc": key_enc,
        "base_url": base,
        "model": body.model.strip() or integrations.RECEIPT_OCR_DEFAULT["model"],
        "timeout_seconds": body.timeout_seconds,
        "tesseract_lang": lang,
    }
    await integrations.save(session, integrations.RECEIPT_OCR_KEY, new)
    # The key itself is never written to the audit trail: only whether it changed.
    record_integration(
        session,
        admin,
        "receipt_ocr.updated",
        "receipt_ocr",
        {**{k: v for k, v in new.items() if k != "api_key_enc"}, "key_changed": body.api_key is not None},
    )
    await session.commit()
    return receipt_ocr_public({**new, "source": "panel"})


@router.post("/receipt-ocr/test")
async def test_receipt_ocr(admin: AdminUser, session: Session):
    """Checks the saved setup end to end without any customer data. Vision: one tiny blank image to the provider."""
    cfg = await integrations.get_receipt_ocr(session)
    c = receipt_ocr.resolve(cfg)
    engine = receipt_ocr.configured_engine(c)
    ok, error, detail = False, None, None
    if engine is None:
        error = "هیچ موتوری فعال نیست: یا «خاموش» است، یا کلید API برای موتور بینایی وارد نشده، یا tesseract نصب نیست."
    elif engine == "tesseract":
        ok, detail = True, "tesseract روی سرور آماده است (دقت به فونت اپ بانک بستگی دارد)."
    else:
        try:
            async with httpx.AsyncClient(timeout=c.timeout) as client:
                r = await client.post(
                    f"{c.base_url.rstrip('/')}/v1/messages",
                    headers={"x-api-key": c.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={
                        "model": c.model,
                        "max_tokens": 5,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": base64.b64encode(_PROBE_PNG).decode(),
                                        },
                                    },
                                    {"type": "text", "text": "Reply with the single word OK."},
                                ],
                            }
                        ],
                    },
                )
            if r.status_code == 200:
                ok, detail = True, "اتصال و مدل تأیید شد."
            elif r.status_code in (401, 403):
                error = "کلید API پذیرفته نشد."
            elif r.status_code == 404:
                error = "مدل یا آدرس سرویس پیدا نشد."
            elif r.status_code == 429:
                error = "سقف درخواست یا اعتبار حساب سرویس تمام شده است."
            else:
                error = f"پاسخ غیرمنتظره از سرویس: HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            error = f"سرور به سرویس وصل نشد ({type(exc).__name__}). دسترسی خروجی HTTPS را بررسی کنید."
    record_integration(session, admin, "receipt_ocr.tested", "receipt_ocr", {"ok": ok, "engine": engine})
    await session.commit()
    return {"ok": ok, "engine": engine, "error": error, "detail": detail}
