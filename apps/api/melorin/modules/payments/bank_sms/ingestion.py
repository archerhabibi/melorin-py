"""Bank SMS auto-verification: ingestion (see ``bank_sms/__init__.py`` for the overall flow)."""

import hashlib

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain import bank_sms as dom
from melorin.kernel.models.payments import BankSmsMessage, BankSmsSource
from melorin.kernel.models.stores import Store
from melorin.modules.payments.bank_sms.config import MAX_SMS_CHARS
from melorin.modules.payments.bank_sms.matching import _notify, match_message


# ---------------------------------------------------------------------------------------------------- ingestion
async def ingest(session: AsyncSession, src: BankSmsSource, text: str, *, sender: str | None = None) -> tuple[BankSmsMessage, bool]:
    """Store one forwarded SMS (idempotent) and try to match it. Returns ``(message, created)``."""
    text = (text or "").strip()
    if not text:
        raise AppError("BANK_SMS_EMPTY", "متن پیامک خالی است.", 422)
    if len(text) > MAX_SMS_CHARS:
        raise AppError("BANK_SMS_TOO_LONG", "متن پیامک بیش از حد طولانی است.", 413)
    sender = (sender or "").strip()[:64] or None
    if src.senders and (sender or "") not in set(src.senders):
        raise AppError("BANK_SMS_SENDER_REJECTED", "فرستنده‌ی پیامک مجاز نیست.", 403)
    store = await session.get(Store, src.store_id)
    src.last_received_at = utcnow()
    try:
        parsed = dom.parse_sms(text, src.bank)
    except dom.SmsParseError as exc:
        fp = hashlib.sha256(("raw:" + dom.normalize_text(text)).encode()).hexdigest()
        existing = await session.scalar(
            select(BankSmsMessage).where(BankSmsMessage.store_id == src.store_id, BankSmsMessage.fingerprint == fp)
        )
        if existing:
            await session.commit()
            return existing, False
        m = BankSmsMessage(
            store_id=src.store_id, source_id=src.id, fingerprint=fp, sender=sender, raw_text=text, status="unparsed", note=str(exc)[:200]
        )
        session.add(m)
        await session.commit()
        return m, True
    existing = await session.scalar(
        select(BankSmsMessage).where(BankSmsMessage.store_id == src.store_id, BankSmsMessage.fingerprint == parsed.fingerprint)
    )
    if existing:
        await session.commit()
        return existing, False
    account = (src.settings or {}).get("account_number")
    if account and parsed.serial != account:
        # The phone forwards every SMS; one that belongs to another account must never pay this store's receipts.
        m = BankSmsMessage(
            store_id=src.store_id,
            source_id=src.id,
            fingerprint=parsed.fingerprint,
            serial=parsed.serial,
            direction=parsed.direction,
            amount_rial=parsed.amount_rial,
            balance_rial=parsed.balance_rial,
            occurred_at=parsed.occurred_at,
            sender=sender,
            raw_text=text,
            status="ignored",
            note="other_account",
        )
        session.add(m)
        await session.commit()
        return m, True
    gap = False
    if parsed.balance_rial is not None and parsed.direction in ("deposit", "withdrawal"):
        prev = await session.scalar(
            select(BankSmsMessage)
            .where(
                BankSmsMessage.store_id == src.store_id,
                BankSmsMessage.balance_rial.is_not(None),
                BankSmsMessage.occurred_at < parsed.occurred_at,
            )
            .order_by(BankSmsMessage.occurred_at.desc())
            .limit(1)
        )
        if prev is not None:
            signed = parsed.amount_rial if parsed.direction == "deposit" else -parsed.amount_rial
            gap = (prev.balance_rial or 0) + signed != parsed.balance_rial
    m = BankSmsMessage(
        store_id=src.store_id,
        source_id=src.id,
        fingerprint=parsed.fingerprint,
        serial=parsed.serial,
        direction=parsed.direction,
        amount_rial=parsed.amount_rial,
        balance_rial=parsed.balance_rial,
        occurred_at=parsed.occurred_at,
        sender=sender,
        raw_text=text,
        status="unmatched" if parsed.direction == "deposit" else "ignored",
        note="withdrawal" if parsed.direction == "withdrawal" else None,
        balance_gap=gap,
    )
    session.add(m)
    try:
        await session.commit()
    except IntegrityError:  # two forwarders delivered the same SMS at once
        await session.rollback()
        dup = await session.scalar(
            select(BankSmsMessage).where(BankSmsMessage.store_id == src.store_id, BankSmsMessage.fingerprint == parsed.fingerprint)
        )
        if dup:
            return dup, False
        raise
    if gap:
        await _notify(
            session,
            src.store_id,
            "⚠️ مانده‌ی پیامک بانک با پیامک قبلی همخوان نیست؛ ممکن است پیامکی دریافت نشده باشد.",
            "payment_sms_balance_gap",
        )
        await session.commit()
    if m.status == "unmatched" and store is not None:
        await match_message(session, m, src, store)
    return m, True
