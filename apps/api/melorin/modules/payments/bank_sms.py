"""Card-to-card auto verification against the bank's deposit SMS.

Flow: the store owner's phone forwards every bank SMS to ``POST /payments/bank-sms/{store_id}`` (token protected) ->
the SMS is parsed and stored once -> it is matched with a customer receipt that waits for review (same amount, the
time printed on the receipt agrees with the SMS, the SMS is not older than the request) -> only an unambiguous match
credits the wallet through the normal ``mark_succeeded`` path (row locks + ledger idempotency key, so a duplicate
SMS, a retry or a race can never credit twice). Everything else stays in the manual review queue.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.domain import bank_sms as dom
from melorin.domain.order_state import PaymentStatus
from melorin.kernel.models.payments import BankSmsMessage, BankSmsSource, Payment
from melorin.kernel.models.stores import Store
from melorin.modules.payments import service as payments

log = logging.getLogger("melorin.payments.bank_sms")
P = PaymentStatus

MAX_SMS_CHARS = 1000
TOKEN_PREFIX = "mlr_sms_"

# (key, kind, minimum, maximum, default) - the single place that defines which tuning knobs exist.
_SETTING_RULES = (
    ("window_minutes", int, 5, 7 * 24 * 60, 720),
    ("time_tolerance_minutes", int, 0, 30, 5),
    ("require_claimed_time", bool, None, None, True),
    ("max_auto_amount_rial", int, 1, 10**13, None),
    ("account_number", str, 8, 26, None),
)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def clean_settings(raw: dict | None) -> dict:
    """Validate the tuning knobs (ordered rule table); unknown keys are rejected, ``None`` resets to the default."""
    raw = dict(raw or {})
    out: dict = {}
    for key, kind, lo, hi, default in _SETTING_RULES:
        if key not in raw:
            continue
        value = raw.pop(key)
        if value is None:
            continue
        if kind is bool:
            if not isinstance(value, bool):
                raise AppError("BANK_SMS_SETTING_INVALID", f"مقدار «{key}» باید درست/نادرست باشد.", 422)
        elif kind is str:
            value = dom.digits_only(value) if isinstance(value, str) else ""
            if not (lo <= len(value) <= hi):
                raise AppError("BANK_SMS_SETTING_INVALID", "شماره حساب باید فقط عدد و بین ۸ تا ۲۶ رقم باشد.", 422)
        else:
            if isinstance(value, bool) or not isinstance(value, int) or not (lo <= value <= hi):
                raise AppError("BANK_SMS_SETTING_INVALID", f"مقدار «{key}» باید عددی بین {lo} و {hi} باشد.", 422)
        out[key] = value
    if raw:
        raise AppError("BANK_SMS_SETTING_INVALID", f"تنظیم ناشناخته: {', '.join(sorted(raw))}", 422)
    return out


def match_settings(source: BankSmsSource) -> dom.MatchSettings:
    s = source.settings or {}
    return dom.MatchSettings(
        window_minutes=int(s.get("window_minutes", 720)),
        time_tolerance_minutes=int(s.get("time_tolerance_minutes", 5)),
        require_claimed_time=bool(s.get("require_claimed_time", True)),
        max_auto_amount_rial=s.get("max_auto_amount_rial"),
    )


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def source_out(src: BankSmsSource | None, *, store_id: uuid.UUID | None = None) -> dict:
    s = src.settings if src else {}
    return {
        "store_id": str(src.store_id if src else store_id),
        "configured": src is not None,
        "bank": src.bank if src else "mehr_iran",
        "is_enabled": src.is_enabled if src else False,
        "auto_verify": src.auto_verify if src else False,
        "has_token": bool(src and src.token_hash),
        "token_hint": src.token_hint if src else None,
        "senders": list(src.senders or []) if src else [],
        "settings": {
            "window_minutes": (s or {}).get("window_minutes", 720),
            "time_tolerance_minutes": (s or {}).get("time_tolerance_minutes", 5),
            "require_claimed_time": (s or {}).get("require_claimed_time", True),
            "max_auto_amount_rial": (s or {}).get("max_auto_amount_rial"),
            "account_number": (s or {}).get("account_number"),
        },
        "last_received_at": src.last_received_at if src else None,
    }


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


# ------------------------------------------------------------------------------------------------ configuration
async def get_source(session: AsyncSession, store_id: uuid.UUID) -> BankSmsSource | None:
    return await session.scalar(select(BankSmsSource).where(BankSmsSource.store_id == store_id))


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


# ----------------------------------------------------------------------------------------------------- matching
async def _candidates(session: AsyncSession, store: Store) -> tuple[list[dom.Candidate], dict[str, Payment]]:
    rows = (
        await session.scalars(
            select(Payment)
            .where(
                Payment.store_id == store.id,
                Payment.provider == "manual_card",
                Payment.purpose == "wallet_topup",
                Payment.status == P.AWAITING_REVIEW,
                Payment.receipt_file_id.is_not(None),
            )
            .order_by(Payment.created_at)
            .limit(500)
        )
    ).all()
    out: list[dom.Candidate] = []
    by_id: dict[str, Payment] = {}
    for p in rows:
        rial = dom.to_rial(p.amount, p.currency)
        if rial is None:
            continue
        claim = (p.meta or {}).get("receipt_claim") or {}
        claimed = None
        if claim.get("paid_at"):
            try:
                claimed = _aware(dt.datetime.fromisoformat(claim["paid_at"]))
            except ValueError:
                claimed = None
        seen = claim.get("amount_rial")
        blocked = "receipt_amount_mismatch" if isinstance(seen, int) and seen != rial else None
        out.append(dom.Candidate(str(p.id), rial, _aware(p.created_at), claimed, blocked))
        by_id[str(p.id)] = p
    return out, by_id


async def _notify(session: AsyncSession, store_id: uuid.UUID, text: str) -> None:
    await events.emit(session, events.EVENT_CENTER, {"store_id": store_id, "topic": "payments", "text": text})


async def _link(
    session: AsyncSession, sms_id: uuid.UUID, payment_id: uuid.UUID, *, by: str, actor_id=None, note: str | None = None
) -> bool:
    """Lock SMS + payment, link them and credit the wallet. ``False`` when someone else got there first."""
    sms = await session.get(BankSmsMessage, sms_id, with_for_update=True, populate_existing=True)
    if sms is None or sms.status == "matched":
        return False
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if p is None or p.store_id != sms.store_id or p.status != P.AWAITING_REVIEW:
        return False
    sms.status, sms.payment_id, sms.matched_by, sms.note = "matched", p.id, by, (note or sms.note)
    p.meta = {**(p.meta or {}), "bank_sms": {"sms_id": str(sms.id), "serial": sms.serial, "by": by}}
    try:
        await session.flush()
        audit.record(
            session,
            "payment.bank_sms_matched",
            actor_id=actor_id,
            actor_type="admin" if by == "admin" else "system",
            entity_type="payment",
            entity_id=p.id,
            store_id=p.store_id,
            data={"sms_id": str(sms.id), "serial": sms.serial, "amount_rial": sms.amount_rial, "by": by},
        )
        await payments.mark_succeeded(
            session,
            p.id,
            actor_id=actor_id,
            actor_type="admin" if by == "admin" else "system",
            note=f"bank_sms:{sms.serial or sms.id}",
        )
    except IntegrityError:
        await session.rollback()
        return False
    except Exception:
        await session.rollback()
        raise
    if by == "auto":
        await _notify(session, p.store_id, f"✅ شارژ خودکار با پیامک بانک\nمبلغ: {p.amount:,}\nشناسه: {p.id}")
        await session.commit()
    return True


async def _confirm_provisional(
    session: AsyncSession, sms: BankSmsMessage, source: BankSmsSource, store: Store, parsed: dom.ParsedSms
) -> bool:
    """A deposit SMS that arrives *after* a receipt was credited provisionally is the proof that was missing: when it
    matches exactly one provisional credit under the usual rules, that credit becomes final without a human."""
    rows = (
        await session.scalars(
            select(Payment)
            .where(Payment.store_id == store.id, Payment.provider == "manual_card", Payment.status == P.SUCCEEDED)
            .order_by(Payment.created_at.desc())
            .limit(200)
        )
    ).all()
    cands, by_id = [], {}
    for p in rows:
        if ((p.meta or {}).get("provisional") or {}).get("state") != "open":
            continue
        rial = dom.to_rial(p.amount, p.currency)
        claim = (p.meta or {}).get("receipt_claim") or {}
        try:
            claimed = _aware(dt.datetime.fromisoformat(claim["paid_at"])) if claim.get("paid_at") else None
        except ValueError:
            claimed = None
        seen = claim.get("amount_rial")
        if rial is not None:
            blocked = "receipt_amount_mismatch" if isinstance(seen, int) and seen != rial else None
            cands.append(dom.Candidate(str(p.id), rial, _aware(p.created_at), claimed, blocked))
            by_id[str(p.id)] = p
    if not cands:
        return False
    decision = dom.decide(parsed, cands, match_settings(source))
    if decision.kind != "matched":
        return False
    p = await session.get(Payment, uuid.UUID(decision.payment_id), with_for_update=True, populate_existing=True)
    sms = await session.get(BankSmsMessage, sms.id, with_for_update=True, populate_existing=True)
    prov = ((p.meta or {}).get("provisional") or {}) if p else {}
    if p is None or sms.status == "matched" or prov.get("state") != "open":
        return False
    sms.status, sms.payment_id, sms.matched_by, sms.note = "matched", p.id, "auto", "confirmed_provisional"
    p.meta = {
        **p.meta,
        "bank_sms": {"sms_id": str(sms.id), "serial": sms.serial, "by": "auto"},
        "provisional": {**prov, "state": "confirmed", "resolved_at": utcnow().isoformat(), "resolved_by": "bank_sms"},
    }
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return False
    audit.record(
        session,
        "payment.provisional_confirmed",
        actor_type="system",
        entity_type="payment",
        entity_id=p.id,
        store_id=p.store_id,
        data={"sms_id": str(sms.id), "by": "bank_sms"},
    )
    await _notify(session, p.store_id, f"✅ تأیید موقت با پیامک بانک نهایی شد\nمبلغ: {p.amount:,}\nشناسه: {p.id}")
    await session.commit()
    return True


async def match_message(session: AsyncSession, sms: BankSmsMessage, source: BankSmsSource, store: Store) -> str:
    """Try to pay one stored SMS. Returns the resulting status."""
    if sms.status not in ("unmatched", "ambiguous") or sms.direction != "deposit" or sms.amount_rial is None:
        return sms.status
    parsed = dom.ParsedSms(
        bank=source.bank,
        direction="deposit",
        amount_rial=sms.amount_rial,
        occurred_at=_aware(sms.occurred_at),
        serial=sms.serial,
        balance_rial=sms.balance_rial,
        fingerprint=sms.fingerprint,
    )
    candidates, _ = await _candidates(session, store)
    decision = dom.decide(parsed, candidates, match_settings(source))
    if (
        decision.kind != "matched"
        and source.is_enabled
        and source.auto_verify
        and await _confirm_provisional(session, sms, source, store, parsed)
    ):
        return "matched"
    if decision.kind == "matched":
        if not (source.is_enabled and source.auto_verify):
            sms.status, sms.note = "unmatched", f"suggested:{decision.payment_id}"
            await session.commit()
            return sms.status
        if await _link(session, sms.id, uuid.UUID(decision.payment_id), by="auto"):
            return "matched"
        await session.refresh(sms)
        return sms.status
    if decision.kind == "ambiguous":
        newly = sms.status != "ambiguous"
        sms.status, sms.note = "ambiguous", "candidates:" + ",".join(decision.candidate_ids)[:270]
        await session.commit()
        if newly:
            await _notify(
                session, sms.store_id, f"⚠️ چند رسید هم‌مبلغ برای یک پیامک بانکی؛ نیاز به بررسی دستی\nمبلغ: {sms.amount_rial:,} ریال"
            )
            await session.commit()
    elif sms.status == "ambiguous":
        sms.status, sms.note = "unmatched", decision.reason
        await session.commit()
    return sms.status


async def reconcile_store(session: AsyncSession, store: Store) -> dict:
    """Re-run matching for every open deposit SMS of a store (receipt uploaded after the SMS, clock skew, ...)."""
    src = await get_source(session, store.id)
    if not src or not src.is_enabled:
        return {"checked": 0, "matched": 0}
    since = utcnow() - dt.timedelta(minutes=match_settings(src).window_minutes + 60)
    ids = (
        await session.scalars(
            select(BankSmsMessage.id)
            .where(
                BankSmsMessage.store_id == store.id,
                BankSmsMessage.status.in_(("unmatched", "ambiguous")),
                BankSmsMessage.direction == "deposit",
                BankSmsMessage.created_at >= since,
            )
            .order_by(BankSmsMessage.occurred_at)
            .limit(200)
        )
    ).all()
    matched = 0
    for sid in ids:
        sms = await session.get(BankSmsMessage, sid, populate_existing=True)
        if sms and await match_message(session, sms, src, store) == "matched":
            matched += 1
    return {"checked": len(ids), "matched": matched}


async def try_auto_verify_payment(session: AsyncSession, payment: Payment) -> bool:
    """Called right after a receipt is attached: the deposit SMS may already be there. Never raises into the caller."""
    try:
        if payment.provider != "manual_card" or payment.status != P.AWAITING_REVIEW:
            return False
        store = await session.get(Store, payment.store_id)
        src = await get_source(session, payment.store_id)
        if not (store and src and src.is_enabled and src.auto_verify):
            return False
        res = await reconcile_store(session, store)
        return res["matched"] > 0
    except Exception:  # an SMS problem must never break the customer's receipt upload
        log.warning("auto verify after receipt failed payment=%s", payment.id, exc_info=True)
        await session.rollback()
        return False


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
            gap = prev.balance_rial + signed != parsed.balance_rial
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
        await _notify(session, src.store_id, "⚠️ مانده‌ی پیامک بانک با پیامک قبلی همخوان نیست؛ ممکن است پیامکی دریافت نشده باشد.")
        await session.commit()
    if m.status == "unmatched" and store is not None:
        await match_message(session, m, src, store)
    return m, True


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
    if p.provider != "manual_card" or p.status != P.AWAITING_REVIEW:
        raise AppError("INVALID_PAYMENT_STATE", "این پرداخت در انتظار بررسی نیست.", 409)
    if not await _link(session, sms.id, p.id, by="admin", actor_id=actor_id):
        raise AppError("BANK_SMS_CONFLICT", "پیامک یا پرداخت هم‌زمان تغییر کرد؛ دوباره تلاش کنید.", 409)
    await session.refresh(sms)
    return sms


async def set_ignored(
    session: AsyncSession, store: Store, sms_id: uuid.UUID, *, ignored: bool, actor_id: uuid.UUID, actor_type: str
) -> BankSmsMessage:
    sms = await session.get(BankSmsMessage, sms_id)
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
