"""Bank SMS auto-verification: matching (see ``bank_sms/__init__.py`` for the overall flow)."""

import datetime as dt
import uuid
from typing import cast

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events
from melorin.core.db import utcnow
from melorin.domain import bank_sms as dom
from melorin.domain.order_state import PaymentStatus
from melorin.kernel.models.payments import BankSmsMessage, BankSmsSource, Payment
from melorin.kernel.models.stores import Store
from melorin.modules.payments import service as payments
from melorin.domain.timeutil import aware as _aware
from melorin.modules.payments.bank_sms.config import match_settings


P = PaymentStatus


# ----------------------------------------------------------------------------------------------------- matching
async def _candidates(
    session: AsyncSession, store: Store, parsed: dom.ParsedSms, settings: dom.MatchSettings, *, include_provisional: bool
) -> tuple[list[dom.Candidate], dict[str, Payment]]:
    """Collect every plausible pending or open provisional receipt before deciding whether the SMS is unique."""
    amount_filters = [and_(Payment.currency == "IRR", Payment.amount == parsed.amount_rial)]
    if parsed.amount_rial % 10 == 0:
        amount_filters.append(and_(Payment.currency == "IRT", Payment.amount == parsed.amount_rial // 10))
    statuses = (P.AWAITING_REVIEW, P.SUCCEEDED) if include_provisional else (P.AWAITING_REVIEW,)
    occurred = cast(dt.datetime, _aware(parsed.occurred_at))
    rows = (
        await session.scalars(
            select(Payment).where(
                Payment.store_id == store.id,
                Payment.provider == "manual_card",
                Payment.purpose == "wallet_topup",
                Payment.status.in_(statuses),
                Payment.receipt_file_id.is_not(None),
                Payment.created_at >= occurred - dt.timedelta(minutes=settings.window_minutes),
                Payment.created_at <= occurred + dt.timedelta(seconds=settings.clock_skew_seconds),
                or_(*amount_filters),
            )
        )
    ).all()
    out: list[dom.Candidate] = []
    by_id: dict[str, Payment] = {}
    for p in rows:
        if p.status == P.SUCCEEDED and ((p.meta or {}).get("provisional") or {}).get("state") != "open":
            continue
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


async def _notify(session: AsyncSession, store_id: uuid.UUID, text: str, kind: str) -> None:
    await events.emit_admin_notice(session, kind, text, store_id=store_id)


async def _link(
    session: AsyncSession, sms_id: uuid.UUID, payment_id: uuid.UUID, *, by: str, actor_id=None, note: str | None = None
) -> bool:
    """Lock SMS + payment, link them and credit the wallet. ``False`` when someone else got there first."""
    sms = await session.get(BankSmsMessage, sms_id, with_for_update=True, populate_existing=True)
    if (
        sms is None
        or sms.status == "matched"
        or sms.direction != "deposit"
        or (by == "auto" and sms.status not in ("unmatched", "ambiguous"))
    ):
        return False
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if (
        p is None
        or p.store_id != sms.store_id
        or p.status != P.AWAITING_REVIEW
        or p.provider != "manual_card"
        or p.purpose != "wallet_topup"
        or dom.to_rial(p.amount, p.currency) != sms.amount_rial
    ):
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
        await _notify(session, p.store_id, f"✅ شارژ خودکار با پیامک بانک\nمبلغ: {p.amount:,}\nشناسه: {p.id}", "payment_sms_matched")
        await session.commit()
    return True


async def _confirm_provisional(
    session: AsyncSession, sms_id: uuid.UUID, payment_id: uuid.UUID, *, by: str = "auto", actor_id=None, actor_type: str = "system"
) -> bool:
    """Confirm a provisional receipt if both records still permit the requested link."""
    sms = await session.get(BankSmsMessage, sms_id, with_for_update=True, populate_existing=True)
    if (
        sms is None
        or sms.status == "matched"
        or sms.direction != "deposit"
        or (by == "auto" and sms.status not in ("unmatched", "ambiguous"))
    ):
        return False
    p = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    prov = ((p.meta or {}).get("provisional") or {}) if p else {}
    if (
        p is None
        or p.store_id != sms.store_id
        or p.status != P.SUCCEEDED
        or p.provider != "manual_card"
        or p.purpose != "wallet_topup"
        or dom.to_rial(p.amount, p.currency) != sms.amount_rial
        or prov.get("state") != "open"
    ):
        return False
    sms.status, sms.payment_id, sms.matched_by, sms.note = "matched", p.id, by, "confirmed_provisional"
    p.meta = {
        **(p.meta or {}),
        "bank_sms": {"sms_id": str(sms.id), "serial": sms.serial, "by": by},
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
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="payment",
        entity_id=p.id,
        store_id=p.store_id,
        data={"sms_id": str(sms.id), "by": by},
    )
    await _notify(session, p.store_id, f"✅ تأیید موقت با پیامک بانک نهایی شد\nمبلغ: {p.amount:,}\nشناسه: {p.id}", "payment_sms_confirmed")
    await session.commit()
    return True


async def match_message(session: AsyncSession, sms: BankSmsMessage, source: BankSmsSource, store: Store) -> str:
    """Try to pay one stored SMS. Returns the resulting status."""
    # Serialize competing matchers and human decisions, and never act on a stale status.
    await session.refresh(sms, with_for_update=True)
    if sms.status not in ("unmatched", "ambiguous") or sms.direction != "deposit" or sms.amount_rial is None:
        return sms.status
    parsed = dom.ParsedSms(
        bank=source.bank,
        direction="deposit",
        amount_rial=sms.amount_rial,
        occurred_at=cast(dt.datetime, _aware(sms.occurred_at)),
        serial=sms.serial,
        balance_rial=sms.balance_rial,
        fingerprint=sms.fingerprint,
    )
    auto = source.is_enabled and source.auto_verify
    settings = match_settings(source)
    candidates, by_id = await _candidates(session, store, parsed, settings, include_provisional=auto)
    decision = dom.decide(parsed, candidates, settings)
    if decision.kind == "matched" and decision.payment_id:
        if not auto:
            sms.status, sms.note = "unmatched", f"suggested:{decision.payment_id}"
            await session.commit()
            return sms.status
        payment_id = uuid.UUID(decision.payment_id)
        if by_id[decision.payment_id].status == P.SUCCEEDED:
            matched = await _confirm_provisional(session, sms.id, payment_id)
        else:
            matched = await _link(session, sms.id, payment_id, by="auto")
        if matched:
            return "matched"
        await session.refresh(sms)
        return sms.status
    if decision.kind == "ambiguous":
        newly = sms.status != "ambiguous"
        sms.status, sms.note = "ambiguous", "candidates:" + ",".join(decision.candidate_ids)[:270]
        await session.commit()
        if newly:
            await _notify(
                session,
                sms.store_id,
                f"⚠️ چند رسید هم‌مبلغ برای یک پیامک بانکی؛ نیاز به بررسی دستی\nمبلغ: {sms.amount_rial:,} ریال",
                "payment_sms_ambiguous",
            )
            await session.commit()
    elif sms.status == "ambiguous":
        sms.status, sms.note = "unmatched", decision.reason
        await session.commit()
    return sms.status
