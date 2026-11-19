"""Receipt OCR as an outbox job (V01 V-21).

The upload request only stores the picture, the fingerprint and whatever the customer typed, then queues one
``payments.receipt_ocr`` event. This job reads the picture later, in the worker:

* a slow or hanging OCR/vision endpoint no longer holds an API worker (it used to hold one for up to 25 s per upload);
* the paid vision call is capped per store per day *here*, so an abusive customer cannot spend the operator's budget;
* the payment keeps ``meta.receipt_ocr.state == "pending"`` until the job is done, and the grace-credit sweep refuses to
  credit a receipt whose reading is still pending (``ocr_pending``) - the proof signal must exist before money moves.

Nothing here raises for an OCR problem: an unreadable receipt simply stays with a human reviewer. Only a database error
escapes (the outbox retries it with back-off).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import integrations
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.core.metrics import inc
from melorin.core.ratelimit import hit
from melorin.core.storage import get_storage
from melorin.domain.order_state import PaymentStatus
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.system import FileObject
from melorin.modules.payments import bank_sms, receipt_ocr

log = logging.getLogger("melorin.payments.ocr_job")
P = PaymentStatus

PENDING, DONE, SKIPPED, STALE = "pending", "done", "skipped", "stale"
MAX_PENDING = dt.timedelta(hours=1)


def pending_state(file_id: uuid.UUID) -> dict:
    return {"state": PENDING, "file_id": str(file_id), "queued_at": utcnow().isoformat()}


def _state(payment: Payment) -> dict:
    return (payment.meta or {}).get("receipt_ocr") or {}


def is_pending(payment: Payment) -> bool:
    return _state(payment).get("state") == PENDING


def blocks_credit(payment: Payment, now: dt.datetime | None = None) -> bool:
    """True while a queued reading may still change what is known about the receipt.

    Bounded, so a dead queue cannot park a customer's money forever (without a reading the usual ``no_proof`` rule applies).
    """
    st = _state(payment)
    if st.get("state") != PENDING:
        return False
    try:
        queued = dt.datetime.fromisoformat(st["queued_at"])
    except (KeyError, ValueError):
        return True
    queued = queued if queued.tzinfo else queued.replace(tzinfo=dt.UTC)
    return (now or utcnow()) - queued < MAX_PENDING


async def _budget_left(store_id: uuid.UUID, engine: str | None) -> bool:
    """Only the paid vision engine is budgeted. A Redis outage fails closed here: the receipt goes to a human."""
    if engine != "vision":
        return True
    try:
        return await hit(f"ocr-daily:{store_id}", get_settings().receipt_ocr_daily_cap, 86400)
    except AppError:  # rate-limit backend down: never spend the budget blind
        log.warning("ocr budget check unavailable store=%s", store_id, exc_info=True)
        return False


async def _finish(session: AsyncSession, payment: Payment, state: dict, claim: dict | None = None) -> None:
    meta = {**(payment.meta or {}), "receipt_ocr": {**state, "finished_at": utcnow().isoformat()}}
    if claim is not None:
        meta["receipt_claim"] = claim
    payment.meta = meta
    await session.commit()


async def run(session: AsyncSession, payload: dict) -> str:
    """Read one queued receipt. Returns the final state (``done``/``skipped``/``stale``) for logs and tests."""
    payment_id, file_id = uuid.UUID(str(payload["payment_id"])), str(payload["file_id"])
    payment = await session.get(Payment, payment_id)
    if payment is None or str(payment.receipt_file_id) != file_id or not is_pending(payment):
        return STALE  # the receipt was replaced, the payment is gone, or an earlier delivery already did the work
    fo = await session.get(FileObject, payment.receipt_file_id)
    if fo is None:
        await _finish(session, payment, {"state": SKIPPED, "reason": "file_missing"})
        return SKIPPED

    cfg = receipt_ocr.resolve(await integrations.get_receipt_ocr(session))
    engine = receipt_ocr.configured_engine(cfg)
    if engine is None:
        await _finish(session, payment, {"state": SKIPPED, "reason": "engine_off"})
        return SKIPPED
    if not await _budget_left(payment.store_id, engine):
        inc("melorin_receipt_ocr_total", result="budget")
        await _finish(session, payment, {"state": SKIPPED, "reason": "daily_budget"})
        return SKIPPED

    storage_key, content_type = fo.storage_key, fo.content_type or ""
    await session.rollback()  # no transaction, no row lock across the OCR call (it may take 25 s)
    data = await get_storage().get(storage_key)
    facts, used = await receipt_ocr.read_receipt(data, content_type, cfg)

    payment = await session.get(Payment, payment_id, with_for_update=True, populate_existing=True)
    if payment is None or str(payment.receipt_file_id) != file_id or not is_pending(payment):
        await session.rollback()
        return STALE  # replaced while the engine was reading
    claim = bank_sms.build_claim(payload.get("typed") or {}, facts, used)
    found = bool(facts is not None and facts.found)
    await _finish(session, payment, {"state": DONE, "engine": used, "read": found}, claim)
    inc("melorin_receipt_ocr_total", result="read" if found else "unreadable")
    if payment.status == P.AWAITING_REVIEW:
        await bank_sms.try_auto_verify_payment(session, payment)  # the deposit SMS may already be waiting for these facts
    return DONE
