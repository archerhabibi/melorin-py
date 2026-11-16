"""Bank SMS auto-verification: reconciliation (see ``bank_sms/__init__.py`` for the overall flow)."""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.kernel.models.payments import BankSmsMessage, Payment
from melorin.kernel.models.stores import Store
from melorin.modules.payments.bank_sms.config import get_source, log, match_settings
from melorin.modules.payments.bank_sms.matching import P, match_message


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
