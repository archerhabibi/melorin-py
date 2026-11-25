"""Loyalty club: adjustments (see ``service.py`` for the facade and the overview)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.loyalty import (
    LoyaltyTransaction,
)
from melorin.kernel.models.stores import Store, StoreMembership
from melorin.modules.loyalty.ledger import _post, get_account


async def adjust(
    session: AsyncSession,
    store: Store,
    user_id: uuid.UUID,
    delta: int,
    *,
    reason: str,
    actor_id: uuid.UUID,
    actor_type: str,
    idempotency_key: str | None = None,
) -> LoyaltyTransaction:
    """Owner/Admin grants (+) or deducts (-) points of one member of THIS store. A deduction never makes the balance negative and
    never lowers the tier (only refunds do). Caller commits."""
    if delta == 0:
        raise AppError("LOYALTY_BAD_ADJUSTMENT", "مقدار تعدیل نمی‌تواند صفر باشد.", 400)
    if not reason.strip():
        raise AppError("LOYALTY_REASON_REQUIRED", "دلیل تعدیل امتیاز را بنویسید.", 400)
    member = await session.scalar(
        select(StoreMembership.id).where(StoreMembership.store_id == store.id, StoreMembership.user_id == user_id)
    )
    if not member and store.owner_user_id != user_id:
        raise NotFound("کاربر")
    acc = await get_account(session, store.id, user_id, lock=True)
    kind = "admin_grant" if delta > 0 else "admin_deduct"
    tx, created = await _post(
        session,
        acc,
        kind=kind,
        amount=delta,
        key=f"loyalty:adjust:{store.id}:{user_id}:{idempotency_key or uuid.uuid4().hex}",
        memo=reason.strip()[:255],
        actor_id=actor_id,
    )
    if not created and (tx.account_id != acc.id or tx.kind != kind or tx.amount != delta):
        raise AppError("IDEMPOTENCY_KEY_REUSED", "این کلید برای تعدیل دیگری استفاده شده است.", 409)
    if created:
        if delta > 0:
            acc.lifetime_earned += delta
        audit.record(
            session,
            "loyalty.points.adjusted",
            actor_id=actor_id,
            actor_type=actor_type,
            entity_type="loyalty_account",
            entity_id=acc.id,
            store_id=store.id,
            data={"user_id": str(user_id), "delta": delta, "reason": reason.strip()[:255]},
        )
    return tx
