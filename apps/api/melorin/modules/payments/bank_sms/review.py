"""Bank SMS auto-verification: review (see ``bank_sms/__init__.py`` for the overall flow)."""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.domain import bank_sms as dom
from melorin.kernel.models.payments import BankSmsMessage, Payment
from melorin.kernel.models.stores import Store
from melorin.domain.timeutil import aware as _aware
from melorin.modules.payments.bank_sms.matching import P, _confirm_provisional, _link


def message_out(m: BankSmsMessage) -> dict:
    return {
        "id": str(m.id),
        "store_id": str(m.store_id),
        "status": m.status,
        "direction": m.direction,
        "amount_rial": m.amount_rial,
        "balance_rial": m.balance_rial,
        "occurred_at": m.occurred_at,
        "serial": m.serial,
        "sender": m.sender,
        "payment_id": str(m.payment_id) if m.payment_id else None,
        "matched_by": m.matched_by,
        "note": m.note,
        "balance_gap": m.balance_gap,
        "created_at": m.created_at,
    }


# -------------------------------------------------------------------------------------------- human decisions
async def list_messages(session: AsyncSession, store_id: uuid.UUID, *, status: str | None = None, limit: int = 100) -> list[BankSmsMessage]:
    q = (
        select(BankSmsMessage)
        .where(BankSmsMessage.store_id == store_id)
        .order_by(BankSmsMessage.created_at.desc())
        .limit(min(max(limit, 1), 300))
    )
    if status:
        q = q.where(BankSmsMessage.status == status)
    return list((await session.scalars(q)).all())


async def manual_link(
    session: AsyncSession, store: Store, sms_id: uuid.UUID, payment_id: uuid.UUID, *, actor_id: uuid.UUID, actor_type: str
) -> BankSmsMessage:
    """A human pairs a deposit with a receipt (e.g. an ambiguous one). Amount must still be identical."""
    sms = await session.get(BankSmsMessage, sms_id)
    p = await session.get(Payment, payment_id)
    if not sms or sms.store_id != store.id:
        raise NotFound("پیامک")
    if not p or p.store_id != store.id:
        raise NotFound("پرداخت")
    if sms.status == "matched":
        raise AppError("BANK_SMS_ALREADY_MATCHED", "این پیامک قبلاً به یک پرداخت وصل شده است.", 409)
    if sms.direction != "deposit" or sms.amount_rial != dom.to_rial(p.amount, p.currency):
        raise AppError("BANK_SMS_AMOUNT_MISMATCH", "مبلغ پیامک با مبلغ پرداخت برابر نیست.", 409)
    provisional = p.status == P.SUCCEEDED and ((p.meta or {}).get("provisional") or {}).get("state") == "open"
    if p.provider != "manual_card" or p.purpose != "wallet_topup" or (p.status != P.AWAITING_REVIEW and not provisional):
        raise AppError("INVALID_PAYMENT_STATE", "این پرداخت در انتظار بررسی نیست.", 409)
    if provisional:
        linked = await _confirm_provisional(session, sms.id, p.id, by="admin", actor_id=actor_id, actor_type=actor_type)
    else:
        linked = await _link(session, sms.id, p.id, by="admin", actor_id=actor_id)
    if not linked:
        raise AppError("BANK_SMS_CONFLICT", "پیامک یا پرداخت هم‌زمان تغییر کرد؛ دوباره تلاش کنید.", 409)
    await session.refresh(sms)
    return sms


async def set_ignored(
    session: AsyncSession, store: Store, sms_id: uuid.UUID, *, ignored: bool, actor_id: uuid.UUID, actor_type: str
) -> BankSmsMessage:
    sms = await session.get(BankSmsMessage, sms_id, with_for_update=True, populate_existing=True)
    if not sms or sms.store_id != store.id:
        raise NotFound("پیامک")
    if sms.status == "matched":
        raise AppError("BANK_SMS_ALREADY_MATCHED", "این پیامک قبلاً به یک پرداخت وصل شده است.", 409)
    sms.status = "ignored" if ignored else ("unmatched" if sms.direction == "deposit" else "ignored")
    audit.record(
        session,
        "bank_sms.ignored" if ignored else "bank_sms.restored",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="bank_sms",
        entity_id=sms.id,
        store_id=store.id,
    )
    await session.commit()
    return sms


def build_claim(customer: dict, facts, engine: str | None) -> dict:
    """What we know about the receipt: the OCR/vision reading, overridden by anything the customer typed explicitly."""
    claim: dict = dict(facts.to_claim()) if facts is not None else {}
    paid = claim.get("paid_at")
    if paid and _aware(dt.datetime.fromisoformat(paid)) > utcnow() + dt.timedelta(minutes=10):
        claim.pop("paid_at")  # a time in the future is a misread, never a fact
    claim.update(customer)
    claim["source"] = "customer" if customer.get("paid_at") else ("ocr" if claim.get("paid_at") else "none")
    if engine:
        claim["ocr_engine"] = engine
        claim["ocr_ok"] = bool(facts is not None and facts.found)
    return claim


def parse_claim(paid_at: str | None, reference: str | None, card_last4: str | None) -> dict:
    """The facts the customer read off the receipt. Stored with the payment; the image itself is never trusted."""
    claim: dict = {}
    if paid_at and paid_at.strip():
        when = dom.parse_datetime_text(paid_at)
        if when is None:
            raise AppError("RECEIPT_TIME_INVALID", "زمان رسید نامعتبر است؛ نمونه: 1405/08/02 22:50", 422)
        if when > utcnow() + dt.timedelta(minutes=10):
            raise AppError("RECEIPT_TIME_INVALID", "زمان رسید در آینده است.", 422)
        claim["paid_at"] = when.isoformat()
    if reference and reference.strip():
        ref = dom.digits_only(reference)
        if not (6 <= len(ref) <= 30):
            raise AppError("RECEIPT_REF_INVALID", "شماره مرجع نامعتبر است.", 422)
        claim["reference"] = ref
    if card_last4 and card_last4.strip():
        last4 = dom.digits_only(card_last4)
        if len(last4) != 4:
            raise AppError("RECEIPT_CARD_INVALID", "۴ رقم آخر کارت مبدأ را وارد کنید.", 422)
        claim["source_card_last4"] = last4
    return claim
