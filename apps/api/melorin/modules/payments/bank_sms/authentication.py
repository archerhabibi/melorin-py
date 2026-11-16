"""Bank SMS auto-verification: authentication (see ``bank_sms/__init__.py`` for the overall flow)."""

import hashlib
import hmac
import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.errors import AppError, NotFound
from melorin.domain import bank_sms as dom
from melorin.kernel.models.payments import BankSmsSource
from melorin.kernel.models.stores import Store
from melorin.modules.payments.bank_sms.config import TOKEN_PREFIX, clean_settings, get_source


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


async def save_source(
    session: AsyncSession,
    store: Store,
    *,
    actor_id: uuid.UUID | None,
    actor_type: str,
    bank: str | None = None,
    is_enabled: bool | None = None,
    auto_verify: bool | None = None,
    senders: list[str] | None = None,
    settings: dict | None = None,
) -> tuple[BankSmsSource, str | None]:
    """Create/update the store's SMS source. Returns ``(source, plaintext_token_or_None)``: the token is only ever
    returned when it is created, so it can be copied once into the SMS forwarder app."""
    if dom.to_rial(1, store.currency) is None:
        raise AppError("BANK_SMS_CURRENCY", "تأیید خودکار فقط برای فروشگاه‌های ریالی/تومانی ممکن است.", 400)
    if bank is not None and bank not in dom.PARSERS:
        raise AppError("BANK_SMS_BANK_UNSUPPORTED", "قالب پیامک این بانک پشتیبانی نمی‌شود.", 400)
    src = await get_source(session, store.id)
    token = None
    if src is None:
        src = BankSmsSource(store_id=store.id, bank=bank or "mehr_iran", is_enabled=True, auto_verify=False)
        session.add(src)
        token = new_token()
        src.token_hash, src.token_hint = hash_token(token), token[-4:]
    if bank is not None:
        src.bank = bank
    if is_enabled is not None:
        src.is_enabled = is_enabled
    if auto_verify is not None:
        src.auto_verify = auto_verify
    if senders is not None:
        cleaned = sorted({x.strip() for x in senders if x and x.strip()})
        if len(cleaned) > 10 or any(len(x) > 40 for x in cleaned):
            raise AppError("BANK_SMS_SETTING_INVALID", "فهرست فرستنده‌ها نامعتبر است.", 422)
        src.senders = cleaned
    if settings is not None:
        src.settings = clean_settings(settings)
    src.updated_by = actor_id
    audit.record(
        session,
        "bank_sms.source_saved",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="store",
        entity_id=store.id,
        store_id=store.id,
        data={"auto_verify": src.auto_verify, "enabled": src.is_enabled, "bank": src.bank, "token_created": token is not None},
    )
    await session.commit()
    return src, token


async def rotate_token(session: AsyncSession, store: Store, *, actor_id: uuid.UUID | None, actor_type: str) -> str:
    src = await get_source(session, store.id)
    if src is None:
        raise NotFound("منبع پیامک")
    token = new_token()
    src.token_hash, src.token_hint, src.updated_by = hash_token(token), token[-4:], actor_id
    audit.record(
        session,
        "bank_sms.token_rotated",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="store",
        entity_id=store.id,
        store_id=store.id,
    )
    await session.commit()
    return token


async def authenticate(session: AsyncSession, store_id: uuid.UUID, token: str | None) -> BankSmsSource:
    """Constant-time check of the webhook token. One generic error for every failure: no store enumeration."""
    src = await get_source(session, store_id)
    given = hash_token(token or "")
    stored = (src.token_hash if src else None) or "0" * 64
    ok = hmac.compare_digest(given, stored)
    if not (src and src.is_enabled and src.token_hash and ok):
        raise AppError("BANK_SMS_UNAUTHORIZED", "دسترسی نامعتبر است.", 401)
    return src
