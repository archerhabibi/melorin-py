"""Duplicate card-receipt detection by image fingerprint (sha256 of the bytes + Telegram ``file_unique_id``).

Bank-SMS auto verification proves a *deposit*; it says nothing about a *picture* being used twice, and many receipts
have no SMS at all (no forwarder, a bank we cannot parse, SMS arrived late). This layer is independent of the SMS: it
answers one question at upload time - "has this exact picture already been attached to another payment?".

Policy, per store (``warn`` is the default, so a false positive never costs a customer money):

* ``warn``  - accept the upload, remember the matches on the payment (``meta.receipt_duplicate``) and tell the reviewers
              which earlier payments used the same picture (event center, review queue, admin list);
* ``block`` - refuse the upload with 409 ``RECEIPT_DUPLICATE`` *before* the file is stored.

Rules that keep the check honest:

* ``sha256`` is computed by the API from the uploaded bytes and is trusted. ``file_unique_id`` is sent by the Telegram bot;
  it is validated for shape only, so it is advisory next to the hash (it can only ever hit the caller's own upload).
* A payment never matches itself: re-uploading the same picture for the same payment is a harmless retry.
* Matches are looked up across all stores (a picture reused in another store is the stronger fraud signal), but what a
  store owner is shown stays inside the owner's own store: other stores are only counted, never named.
* ``block`` ignores matches against payments that are already ``failed`` / ``cancelled`` (a customer whose receipt was
  rejected by mistake may send it again); ``warn`` still lists them, with their status.
"""

from __future__ import annotations

import dataclasses
import re
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, settings_store
from melorin.core.errors import AppError
from melorin.domain.order_state import PaymentStatus
from melorin.kernel.models.payments import Payment, PaymentReceiptFingerprint
from melorin.kernel.models.stores import Store

KEY = "payments.receipt_dup.{}"
POLICIES = ("warn", "block")
DEFAULT_POLICY = "warn"
MAX_MATCHES = 20
_DEAD = (PaymentStatus.FAILED, PaymentStatus.CANCELLED)
_FILE_UNIQUE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

BLOCK_MESSAGE = (
    "این تصویر رسید قبلاً برای پرداخت دیگری ثبت شده و طبق تنظیمات فروشگاه پذیرفته نمی‌شود. اگر اشتباه است با پشتیبانی تماس بگیرید."
)


@dataclasses.dataclass(frozen=True)
class Match:
    payment_id: uuid.UUID
    store_id: uuid.UUID
    status: str
    by: tuple[str, ...]  # which fingerprint matched: "sha256" and/or "file_unique_id"

    @property
    def live(self) -> bool:
        return self.status not in _DEAD


def clean_file_unique_id(raw: str | None) -> str | None:
    """Telegram's file_unique_id is short URL-safe text; anything else is dropped instead of stored."""
    value = (raw or "").strip()
    return value if _FILE_UNIQUE_ID.match(value) else None


async def get_policy(session: AsyncSession, store_id: uuid.UUID) -> str:
    stored = await settings_store.get(session, KEY.format(store_id))
    policy = stored.get("policy") if isinstance(stored, dict) else None
    return policy if policy in POLICIES else DEFAULT_POLICY


async def save_policy(session: AsyncSession, store: Store, policy: str, *, actor_id, actor_type: str) -> dict:
    if policy not in POLICIES:
        raise AppError("RECEIPT_DUP_POLICY_INVALID", "سیاست رسید تکراری باید warn یا block باشد.", 422)
    await settings_store.set_value(session, KEY.format(store.id), {"policy": policy})
    audit.record(
        session,
        "payments.receipt_dup_policy",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="store",
        entity_id=store.id,
        store_id=store.id,
        data={"policy": policy},
    )
    await session.commit()
    return {"policy": policy}


async def find_matches(
    session: AsyncSession,
    *,
    sha256: str | None,
    file_unique_id: str | None,
    exclude_payment_id: uuid.UUID | None = None,
) -> list[Match]:
    """Other payments that used the same picture, oldest first (at most ``MAX_MATCHES``)."""
    digest = (sha256 or "").strip().lower() or None
    fid = clean_file_unique_id(file_unique_id)
    clauses = []
    if digest:
        clauses.append(PaymentReceiptFingerprint.sha256 == digest)
    if fid:
        clauses.append(PaymentReceiptFingerprint.file_unique_id == fid)
    if not clauses:
        return []
    q = (
        select(PaymentReceiptFingerprint, Payment.status, Payment.store_id)
        .join(Payment, Payment.id == PaymentReceiptFingerprint.payment_id)
        .where(or_(*clauses))
        .order_by(PaymentReceiptFingerprint.created_at.asc(), PaymentReceiptFingerprint.id.asc())
    )
    if exclude_payment_id is not None:
        q = q.where(PaymentReceiptFingerprint.payment_id != exclude_payment_id)
    merged: dict[uuid.UUID, Match] = {}
    for fp, status, store_id in (await session.execute(q)).all():
        by = tuple(
            name for name, hit in (("sha256", digest and fp.sha256 == digest), ("file_unique_id", fid and fp.file_unique_id == fid)) if hit
        )
        old = merged.get(fp.payment_id)
        merged[fp.payment_id] = Match(fp.payment_id, store_id, str(status), tuple(sorted({*(old.by if old else ()), *by})))
    return list(merged.values())[:MAX_MATCHES]


async def matches_for_payment(session: AsyncSession, payment_id: uuid.UUID) -> list[Match]:
    """Everything that shares a picture with this payment, judged from the fingerprints it stored (current, not upload-time)."""
    rows = (await session.scalars(select(PaymentReceiptFingerprint).where(PaymentReceiptFingerprint.payment_id == payment_id))).all()
    found: dict[uuid.UUID, Match] = {}
    for fp in rows:
        for m in await find_matches(session, sha256=fp.sha256, file_unique_id=fp.file_unique_id, exclude_payment_id=payment_id):
            old = found.get(m.payment_id)
            found[m.payment_id] = dataclasses.replace(m, by=tuple(sorted({*(old.by if old else ()), *m.by})))
    return list(found.values())[:MAX_MATCHES]


def reject_if_blocked(policy: str, matches: list[Match]) -> None:
    """Raise 409 when the store blocks duplicates and a live payment already used this picture."""
    if policy == "block" and any(m.live for m in matches):
        raise AppError("RECEIPT_DUPLICATE", BLOCK_MESSAGE, 409)


async def store_fingerprint(
    session: AsyncSession, payment: Payment, *, sha256: str | None, file_unique_id: str | None
) -> PaymentReceiptFingerprint | None:
    """Remember this upload's fingerprint (flush only; the caller commits). A replaced receipt keeps its older rows."""
    digest = (sha256 or "").strip().lower() or None
    fid = clean_file_unique_id(file_unique_id)
    if not digest and not fid:
        return None
    row = PaymentReceiptFingerprint(payment_id=payment.id, store_id=payment.store_id, sha256=digest, file_unique_id=fid)
    session.add(row)
    await session.flush()
    return row


def summarize(matches: list[Match], *, store_id: uuid.UUID) -> dict | None:
    """The reviewer-facing record kept on ``payment.meta``: own-store payments by id, other stores only counted."""
    if not matches:
        return None
    own = [m for m in matches if m.store_id == store_id]
    return {
        "payments": [{"id": str(m.payment_id), "status": m.status, "by": list(m.by)} for m in own],
        "other_stores": sum(1 for m in matches if m.store_id != store_id),
    }


def warning_text(summary: dict | None) -> str:
    """One Persian line for the event center / review queue."""
    if not summary:
        return ""
    parts = []
    own = summary.get("payments") or []
    if own:
        shown = "، ".join(p["id"][:8] for p in own[:5])
        parts.append(f"{shown}" + (f" (+{len(own) - 5})" if len(own) > 5 else ""))
    if summary.get("other_stores"):
        parts.append(f"{summary['other_stores']} پرداخت در فروشگاه دیگر")
    return "⚠️ رسید تکراری: همین تصویر قبلاً برای پرداخت " + " و ".join(parts) + " ثبت شده است." if parts else ""
