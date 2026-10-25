"""Time-boxed manual review of card-to-card receipts ("grace approval").

An unclear receipt goes to a human. A customer must not wait for a human who is offline, so once a receipt has waited
``minutes`` (default 5) without anyone confirming or rejecting it, the wallet is credited *provisionally* and the payment
joins a fast-review queue. The first admin / reseller who comes online confirms it (the credit stays) or revokes it (the
credit is reversed through the ledger). Guards - a provisional credit is a loan of trust, so it is capped and never
given to anything that looks wrong:

* off by default per store, with a per-receipt amount cap, a store-wide exposure cap and a per-customer open limit;
* never for a receipt whose read amount differs from the request, a receipt image already used for another payment,
  a reference number already seen, or a customer who ever had a provisional credit revoked;
* a deposit SMS that later matches a provisional payment confirms it automatically (the SMS is the proof);
* every step is audited and the credit goes through the same ledger path as any other top-up (idempotent).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events, settings_store
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.domain import bank_sms as dom
from melorin.domain.order_state import PaymentStatus
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import FileObject
from melorin.modules.payments import service as payments
from melorin.modules.wallet import service as wallet

log = logging.getLogger(__name__)
P = PaymentStatus
KEY = "payments.grace.{}"
DEFAULT: dict = {"enabled": False, "minutes": 5, "max_amount_rial": 5_000_000, "max_exposure_rial": 20_000_000, "max_open_per_user": 1}
_RULES = (
    ("enabled", bool, None, None),
    ("minutes", int, 1, 60),
    ("max_amount_rial", int, 1, 10**12),
    ("max_exposure_rial", int, 1, 10**13),
    ("max_open_per_user", int, 1, 10),
)
BLOCK_TEXT = {
    "amount_mismatch": "مبلغ خوانده‌شده از رسید با مبلغ درخواست یکی نیست",
    "over_amount_cap": "مبلغ از سقف تأیید موقت بیشتر است",
    "over_exposure_cap": "سقف کل اعتبارهای موقت باز فروشگاه پر است",
    "user_open_limit": "مشتری هم‌اکنون یک اعتبار موقت بازبینی‌نشده دارد",
    "user_revoked_before": "برای این مشتری قبلاً اعتبار موقت لغو شده است",
    "duplicate_image": "همین تصویر رسید قبلاً برای پرداخت دیگری ثبت شده",
    "duplicate_reference": "شماره مرجع این رسید قبلاً دیده شده",
    "currency": "ارز این پرداخت قابل بررسی نیست",
}


def _aware(v: dt.datetime | None) -> dt.datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=dt.UTC))


async def get_config(session: AsyncSession, store_id: uuid.UUID) -> dict:
    stored = await settings_store.get(session, KEY.format(store_id))
    return {**DEFAULT, **(stored if isinstance(stored, dict) else {})}


def clean(raw: dict) -> dict:
    raw, out = dict(raw), {}
    for key, kind, lo, hi in _RULES:
        if key not in raw:
            continue
        v = raw.pop(key)
        bad = (not isinstance(v, bool)) if kind is bool else (isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi)
        if bad:
            raise AppError("GRACE_SETTING_INVALID", f"مقدار «{key}» نامعتبر است.", 422)
        out[key] = v
    if raw:
        raise AppError("GRACE_SETTING_INVALID", f"تنظیم ناشناخته: {', '.join(sorted(raw))}", 422)
    return out


async def save_config(session: AsyncSession, store: Store, raw: dict, *, actor_id, actor_type: str) -> dict:
    new = {**await get_config(session, store.id), **clean(raw)}
    await settings_store.set_value(session, KEY.format(store.id), new)
    audit.record(
        session,
        "payments.grace_settings",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="store",
        entity_id=store.id,
        store_id=store.id,
        data=new,
    )
    await session.commit()
    return new


def state(p: Payment) -> dict | None:
    return (p.meta or {}).get("provisional")


def _receipt_time(p: Payment) -> dt.datetime:
    raw = (p.meta or {}).get("receipt_attached_at")
    try:
        if raw:
            return _aware(dt.datetime.fromisoformat(raw))
    except ValueError:
        pass
    return _aware(getattr(p, "updated_at", None) or p.created_at)


def auto_approve_at(p: Payment, cfg: dict) -> dt.datetime:
    return _receipt_time(p) + dt.timedelta(minutes=int(cfg["minutes"]))


async def _store_payments(session: AsyncSession, store_id: uuid.UUID, *, limit: int = 400) -> list[Payment]:
    return list(
        (
            await session.scalars(
                select(Payment)
                .where(Payment.store_id == store_id, Payment.provider == "manual_card", Payment.purpose == "wallet_topup")
                .order_by(Payment.created_at.desc())
                .limit(limit)
            )
        ).all()
    )


def _rial(p: Payment) -> int:
    return dom.to_rial(p.amount, p.currency) or 0


async def _block_reason(session: AsyncSession, p: Payment, cfg: dict, history: list[Payment]) -> str | None:
    rial = dom.to_rial(p.amount, p.currency)
    if rial is None:
        return "currency"
    claim = (p.meta or {}).get("receipt_claim") or {}
    seen = claim.get("amount_rial")
    if isinstance(seen, int) and seen != rial:
        return "amount_mismatch"
    if rial > int(cfg["max_amount_rial"]):
        return "over_amount_cap"
    open_rows = [x for x in history if (state(x) or {}).get("state") == "open"]
    if sum(_rial(x) for x in open_rows) + rial > int(cfg["max_exposure_rial"]):
        return "over_exposure_cap"
    mine = [x for x in history if x.user_id == p.user_id]
    if sum(1 for x in mine if (state(x) or {}).get("state") == "open") >= int(cfg["max_open_per_user"]):
        return "user_open_limit"
    if any((state(x) or {}).get("state") == "revoked" for x in mine):
        return "user_revoked_before"
    ref = claim.get("reference")
    if ref and any(x.id != p.id and ((x.meta or {}).get("receipt_claim") or {}).get("reference") == ref for x in history):
        return "duplicate_reference"
    if p.receipt_file_id:
        sha = await session.scalar(select(FileObject.sha256).where(FileObject.id == p.receipt_file_id))
        if sha and await session.scalar(
            select(Payment.id)
            .join(FileObject, FileObject.id == Payment.receipt_file_id)
            .where(FileObject.sha256 == sha, Payment.id != p.id)
            .limit(1)
        ):
            return "duplicate_image"
    return None


async def _notify(session: AsyncSession, store_id: uuid.UUID, text: str) -> None:
    await events.emit(session, events.EVENT_CENTER, {"store_id": store_id, "topic": "payments", "text": text})


async def _approve(session: AsyncSession, p: Payment, cfg: dict) -> bool:
    """Credit one waiting receipt provisionally. Returns False (and writes nothing) if a human or an SMS got there first.

    The row is locked and re-read *before* the decision: the candidate list was read earlier, so an admin may have
    confirmed/rejected the payment since. Without this a stale candidate produced a false "provisional credit" audit
    record and notification (or a 409 that aborted the whole sweep).
    """
    locked = await session.get(Payment, p.id, with_for_update=True, populate_existing=True)
    if locked is None or locked.status != P.AWAITING_REVIEW or (state(locked) or {}).get("state") in ("open", "confirmed", "revoked"):
        await session.commit()  # nothing changed: just release the row lock (a rollback would expire every loaded row)
        return False
    p = locked
    p.meta = {
        **(p.meta or {}),
        "provisional": {
            "state": "open",
            "credited_at": utcnow().isoformat(),
            "grace_minutes": int(cfg["minutes"]),
            "reason": "review_timeout",
        },
    }
    await session.flush()
    await payments.mark_succeeded(session, p.id, actor_type="system", note="grace_timeout")
    audit.record(
        session,
        "payment.provisional_credited",
        actor_type="system",
        entity_type="payment",
        entity_id=p.id,
        store_id=p.store_id,
        data={"amount": p.amount, "grace_minutes": int(cfg["minutes"])},
    )
    await _notify(
        session,
        p.store_id,
        f"⏳ تأیید موقت پس از {int(cfg['minutes'])} دقیقه بدون بررسی\nمبلغ: {p.amount:,}\nلطفاً هرچه زودتر بررسی کنید.\nشناسه: {p.id}",
    )
    await session.commit()
    return True


async def run_store(session: AsyncSession, store: Store, *, now: dt.datetime | None = None) -> dict:
    """Credit provisionally every receipt of this store that waited long enough and passes every guard."""
    store_id = store.id  # keep the plain id: a rollback below expires every ORM object, `store` included
    cfg = await get_config(session, store_id)
    out = {"credited": 0, "blocked": {}}
    if not cfg["enabled"]:
        return out
    now = now or utcnow()
    history = await _store_payments(session, store_id)
    waiting_ids = [
        x.id for x in sorted((x for x in history if x.status == P.AWAITING_REVIEW and x.receipt_file_id), key=lambda x: x.created_at)
    ]
    for pid in waiting_ids:
        p = next((x for x in history if x.id == pid), None)
        if p is None or now < auto_approve_at(p, cfg) or (state(p) or {}).get("state") in ("blocked",):
            continue
        reason = await _block_reason(session, p, cfg, history)
        if reason:
            if (state(p) or {}).get("block") != reason:  # tell the humans once why this one was NOT auto-approved
                p.meta = {**(p.meta or {}), "provisional": {"state": "blocked", "block": reason}}
                await _notify(
                    session, p.store_id, f"🔎 این رسید تأیید موقت نمی‌شود: {BLOCK_TEXT[reason]}\nمبلغ: {p.amount:,}\nشناسه: {p.id}"
                )
                await session.commit()
            out["blocked"][reason] = out["blocked"].get(reason, 0) + 1
            continue
        try:
            if await _approve(session, p, cfg):
                out["credited"] += 1
        except Exception:  # one bad payment must not stop the others from being reviewed on time
            await session.rollback()  # expires every loaded row, so re-read the history before the next receipt
            log.warning("provisional credit failed for payment %s", pid, exc_info=True)
            out["failed"] = out.get("failed", 0) + 1
            history = await _store_payments(session, store_id)
    return out


async def sweep(session: AsyncSession) -> int:
    """Worker entry: every store that has a receipt waiting. Idempotent (a second pass finds nothing left to do)."""
    ids = (
        await session.scalars(
            select(Payment.store_id)
            .where(Payment.status == P.AWAITING_REVIEW, Payment.provider == "manual_card", Payment.receipt_file_id.is_not(None))
            .distinct()
        )
    ).all()
    total = 0
    for sid in ids:
        store = await session.get(Store, sid)
        if store:
            total += (await run_store(session, store))["credited"]
    return total


def _item(p: Payment, cfg: dict) -> dict:
    s = state(p) or {}
    claim = (p.meta or {}).get("receipt_claim") or {}
    return {
        "payment_id": str(p.id),
        "user_id": str(p.user_id),
        "amount": p.amount,
        "currency": p.currency,
        "created_at": p.created_at,
        "state": s.get("state") or "waiting",
        "block": s.get("block"),
        "block_text": BLOCK_TEXT.get(s.get("block") or ""),
        "auto_approve_at": auto_approve_at(p, cfg) if p.status == P.AWAITING_REVIEW else None,
        "credited_at": s.get("credited_at"),
        "resolved_at": s.get("resolved_at"),
        "resolved_by": s.get("resolved_by"),
        "shortfall": s.get("shortfall"),
        "receipt_read": {k: claim.get(k) for k in ("paid_at", "amount_rial", "source_card_last4", "reference", "ocr_engine")}
        if claim
        else None,
    }


async def queue(session: AsyncSession, store_id: uuid.UUID) -> dict:
    cfg = await get_config(session, store_id)
    rows = await _store_payments(session, store_id, limit=200)
    waiting = [x for x in rows if x.status == P.AWAITING_REVIEW and x.receipt_file_id]
    open_ = [x for x in rows if (state(x) or {}).get("state") == "open"]
    done = [x for x in rows if (state(x) or {}).get("state") in ("confirmed", "revoked")][:20]
    return {
        "config": cfg,
        "now": utcnow(),
        "waiting": [_item(x, cfg) for x in sorted(waiting, key=lambda x: x.created_at)],
        "provisional": [_item(x, cfg) for x in sorted(open_, key=lambda x: x.created_at)],
        "recent": [_item(x, cfg) for x in done],
        "exposure_rial": sum(_rial(x) for x in open_),
    }


async def resolve(
    session: AsyncSession, store_id: uuid.UUID, payment_id: uuid.UUID, *, approve: bool, actor_id, actor_type: str, note: str | None = None
) -> Payment:
    """One human decision for a waiting receipt or a provisional credit. Idempotent for repeated clicks."""
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if not p or p.store_id != store_id:
        raise NotFound("پرداخت")
    if p.provider != "manual_card":
        raise AppError("PAYMENT_REVIEW_FORBIDDEN", "تأیید پرداخت‌های درگاه فقط پس از callback معتبر انجام می‌شود.", 403)
    s = state(p) or {}
    if s.get("state") != "open":  # ordinary receipt (or a decision already made): the normal path
        if approve:
            return await payments.mark_succeeded(session, p.id, actor_id=actor_id, actor_type=actor_type, note=note)
        return await payments.mark_failed(session, p.id, actor_id=actor_id, reason=note)
    done = {"resolved_at": utcnow().isoformat(), "resolved_by": str(actor_id) if actor_id else None}
    if approve:
        p.meta = {**p.meta, "provisional": {**s, **done, "state": "confirmed"}}
        audit.record(
            session,
            "payment.provisional_confirmed",
            actor_id=actor_id,
            actor_type=actor_type,
            entity_type="payment",
            entity_id=p.id,
            store_id=p.store_id,
        )
        await session.commit()
        return p
    tx = await wallet.find_tx(session, f"payment:{p.id}")
    if tx:
        await wallet.reverse(
            session, tx, key=f"payment:{p.id}:provisional_revoke", kind="topup_refund", actor_id=actor_id, memo=note or "لغو تأیید موقت"
        )
    w = await wallet.get_wallet(session, p.user_id, p.store_id, currency=p.currency)
    short = max(0, -int(getattr(w, "balance", 0) or 0))
    p.status = P.FAILED
    p.reviewed_by, p.reviewed_at = actor_id, utcnow()
    p.meta = {**p.meta, "provisional": {**s, **done, "state": "revoked", "shortfall": short or None}}
    audit.record(
        session,
        "payment.provisional_revoked",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="payment",
        entity_id=p.id,
        store_id=p.store_id,
        data={"shortfall": short, "note": note},
    )
    await events.emit(
        session,
        events.NOTIFY,
        {
            "user_id": p.user_id,
            "store_id": p.store_id,
            "kind": "payment",
            "title": "شارژ موقت لغو شد",
            "body": note or "رسید شما پس از بررسی تأیید نشد و شارژ موقت برگشت خورد.",
        },
    )
    await session.commit()
    return p
