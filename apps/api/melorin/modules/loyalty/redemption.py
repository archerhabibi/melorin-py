"""Loyalty club: redemption (see ``service.py`` for the facade and the overview)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import events
from melorin.core.errors import AppError, NotFound
from melorin.domain import loyalty as rules
from melorin.domain.loyalty import LoyaltyError, Reward
from melorin.kernel.models.identity import User
from melorin.kernel.models.loyalty import (
    LoyaltyRedemption,
    LoyaltyReward,
)
from melorin.kernel.models.stores import Store
from melorin.modules.wallet import service as wallet
from melorin.modules.loyalty.common import _fail, _now
from melorin.modules.loyalty.ledger import _post, get_account
from melorin.modules.loyalty.program import get_program


# ---------------------------------------------------------------- redeeming
async def redeem(
    session: AsyncSession, store: Store, user: User, reward_id: uuid.UUID, *, idempotency_key: str | None = None
) -> tuple[LoyaltyRedemption, bool]:
    """Spend the customer's points on one reward of THIS store. Returns (redemption, created); a retry with the same key
    returns the first redemption and spends nothing more. The caller commits."""
    row = await get_program(session, store.id)
    if not row or not row.is_enabled:
        raise AppError("LOYALTY_DISABLED", "باشگاه مشتریان این فروشگاه فعال نیست.", 400)
    key = (idempotency_key or uuid.uuid4().hex)[:100]
    replay = await session.scalar(
        select(LoyaltyRedemption).where(
            LoyaltyRedemption.store_id == store.id, LoyaltyRedemption.user_id == user.id, LoyaltyRedemption.idempotency_key == key
        )
    )
    if replay:
        if replay.reward_id != reward_id:
            raise AppError("IDEMPOTENCY_KEY_REUSED", "این کلید برای جایزهٔ دیگری استفاده شده است.", 409)
        return replay, False
    acc = await get_account(session, store.id, user.id, lock=True)
    reward = await session.scalar(
        select(LoyaltyReward)
        .where(LoyaltyReward.id == reward_id, LoyaltyReward.store_id == store.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not reward:
        raise NotFound("جایزه")
    used = await session.scalar(
        select(func.count())
        .select_from(LoyaltyRedemption)
        .where(LoyaltyRedemption.user_id == user.id, LoyaltyRedemption.reward_id == reward.id)
    )
    try:
        rules.check_redeem(
            Reward(
                reward.kind, reward.value, reward.cost_points, reward.stock, reward.redeemed_count, reward.per_user_limit, reward.is_active
            ),
            acc.balance,
            int(used or 0),
        )
    except LoyaltyError as e:
        raise _fail(e) from e
    redemption = LoyaltyRedemption(
        store_id=store.id,
        user_id=user.id,
        reward_id=reward.id,
        points_spent=reward.cost_points,
        value=reward.value,
        currency=store.currency,
        idempotency_key=key,
        created_by=user.id,
    )
    try:
        async with session.begin_nested():
            session.add(redemption)
            await session.flush()
    except IntegrityError:  # the same retry racing itself: the other request won, return its result
        again = await session.scalar(
            select(LoyaltyRedemption).where(
                LoyaltyRedemption.store_id == store.id, LoyaltyRedemption.user_id == user.id, LoyaltyRedemption.idempotency_key == key
            )
        )
        if again:
            return again, False
        raise
    ptx, _ = await _post(
        session,
        acc,
        kind="redeem",
        amount=-reward.cost_points,
        key=f"loyalty:redeem:{redemption.id}",
        reward_id=reward.id,
        memo=f"دریافت جایزه: {reward.name}",
        actor_id=user.id,
    )
    w = await wallet.get_wallet(session, user.id, store.id, currency=store.currency)
    ltx, _ = await wallet.post(
        session,
        kind="loyalty_reward",
        key=f"loyalty:redeem:{redemption.id}",
        currency=store.currency,
        store_id=store.id,
        postings=[wallet.Posting(reward.value, wallet=w), wallet.Posting(-reward.value, account=wallet.acc_loyalty_expense(store.id))],
        memo=f"جایزه باشگاه مشتریان: {reward.name}",
        actor_id=user.id,
    )
    reward.redeemed_count += 1
    redemption.points_tx_id, redemption.ledger_tx_id, redemption.completed_at = ptx.id, ltx.id, _now()
    await events.emit_user_notice(
        session,
        user.id,
        store.id,
        "loyalty",
        "جایزه باشگاه مشتریان",
        f"مبلغ {reward.value:,} {store.currency} بابت «{reward.name}» به کیف پول شما اضافه شد.",
        dedup_key=f"notify:loyalty:redeem:{redemption.id}",
    )
    return redemption, True
