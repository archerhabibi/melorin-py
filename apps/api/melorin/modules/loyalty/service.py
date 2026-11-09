"""Customer loyalty club - one self-contained club PER STORE (docs/22).

Everything here belongs to ONE store: the program, the ladder, the rewards, every customer's purse and the expense account the
rewards are paid from. Nothing crosses stores, exactly like the referral programme (docs/17). Points are earned when an order
completes and taken back when it is refunded; a refund the customer already spent becomes a points debt recovered from his next
earnings, so a balance never goes negative. Every posting carries an idempotency key, so the outbox can retry safely.
"""

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events
from melorin.core.errors import AppError, NotFound
from melorin.domain import loyalty as rules
from melorin.domain.loyalty import EARN_KINDS, LoyaltyError, Program, Reward, Tier
from melorin.domain.order_kinds import is_revenue, revenue_only
from melorin.domain.order_state import OrderStatus
from melorin.kernel.models.identity import User
from melorin.kernel.models.loyalty import (
    LoyaltyAccount,
    LoyaltyProgram,
    LoyaltyRedemption,
    LoyaltyReward,
    LoyaltyTier,
    LoyaltyTransaction,
)
from melorin.kernel.models.orders import Order
from melorin.kernel.models.referral import ReferralRelationship
from melorin.kernel.models.stores import Store, StoreMembership
from melorin.modules.wallet import service as wallet

HISTORY_MAX = 100
_REVERSIBLE = ("order_earn", "first_order_bonus", "referral_bonus")  # earnings that belong to an order and go back with it


def _fail(e: LoyaltyError) -> AppError:
    return AppError(e.code, e.message, 400)


# ---------------------------------------------------------------- program and ladder
def program_rules(row: LoyaltyProgram) -> Program:
    return Program(
        earn_unit=row.earn_unit,
        points_per_unit=row.points_per_unit,
        max_points_per_order=row.max_points_per_order,
        first_order_bonus=row.first_order_bonus,
        referral_bonus=row.referral_bonus,
    )


async def get_program(session: AsyncSession, store_id: uuid.UUID) -> LoyaltyProgram | None:
    return await session.scalar(select(LoyaltyProgram).where(LoyaltyProgram.store_id == store_id))


async def load_tiers(session: AsyncSession, store_id: uuid.UUID) -> list[LoyaltyTier]:
    q = select(LoyaltyTier).where(LoyaltyTier.store_id == store_id).order_by(LoyaltyTier.min_points)
    return list((await session.scalars(q)).all())


def ladder(rows: list[LoyaltyTier]) -> list[Tier]:
    return [Tier(r.name, r.min_points, r.multiplier_bp) for r in rows]


async def ensure_program(session: AsyncSession, store: Store) -> LoyaltyProgram:
    """The store's program row (created disabled with the default ladder on first use)."""
    row = await get_program(session, store.id)
    if row:
        return row
    try:  # two first requests racing each other: the unique key lets one win
        async with session.begin_nested():
            row = LoyaltyProgram(store_id=store.id, is_enabled=False)
            session.add(row)
            await session.flush()
    except IntegrityError:
        return await get_program(session, store.id)  # type: ignore[return-value]
    if not await load_tiers(session, store.id):
        session.add_all(
            LoyaltyTier(store_id=store.id, name=t.name, min_points=t.min_points, multiplier_bp=t.multiplier_bp) for t in rules.DEFAULT_TIERS
        )
        await session.flush()
    return row


def program_out(row: LoyaltyProgram | None) -> dict:
    if row is None:
        return {
            "enabled": False,
            "earn_unit": None,
            "points_per_unit": None,
            "max_points_per_order": None,
            "first_order_bonus": 0,
            "referral_bonus": 0,
        }
    return {
        "enabled": row.is_enabled,
        "earn_unit": row.earn_unit,
        "points_per_unit": row.points_per_unit,
        "max_points_per_order": row.max_points_per_order,
        "first_order_bonus": row.first_order_bonus,
        "referral_bonus": row.referral_bonus,
    }


def tier_out(t: LoyaltyTier) -> dict:
    return {"id": t.id, "name": t.name, "min_points": t.min_points, "multiplier_bp": t.multiplier_bp}


def reward_out(r: LoyaltyReward) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "kind": r.kind,
        "value": r.value,
        "cost_points": r.cost_points,
        "stock": r.stock,
        "remaining": None if r.stock is None else max(0, r.stock - r.redeemed_count),
        "per_user_limit": r.per_user_limit,
        "redeemed_count": r.redeemed_count,
        "sort_order": r.sort_order,
        "is_active": r.is_active,
    }


async def upsert_program(
    session: AsyncSession,
    store: Store,
    *,
    enabled: bool,
    earn_unit: int,
    points_per_unit: int,
    max_points_per_order: int | None,
    first_order_bonus: int,
    referral_bonus: int,
    actor_id: uuid.UUID,
    actor_type: str,
) -> LoyaltyProgram:
    """Change the earning rules of ONE store. The caller has already proven it may act on ``store``; the caller commits."""
    program = Program(earn_unit, points_per_unit, max_points_per_order, first_order_bonus, referral_bonus)
    try:
        rules.validate_program(program)
    except LoyaltyError as e:
        raise _fail(e) from e
    row = await ensure_program(session, store)
    before = program_out(row)
    row.is_enabled, row.earn_unit, row.points_per_unit = enabled, earn_unit, points_per_unit
    row.max_points_per_order, row.first_order_bonus, row.referral_bonus = max_points_per_order, first_order_bonus, referral_bonus
    await session.flush()
    audit.record(
        session,
        "loyalty.program.saved",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="loyalty_program",
        entity_id=row.id,
        store_id=store.id,
        data={"before": before, "after": program_out(row)},
    )
    return row


async def replace_tiers(
    session: AsyncSession, store: Store, tiers: list[Tier], *, actor_id: uuid.UUID, actor_type: str
) -> list[LoyaltyTier]:
    """Replace the whole ladder of ONE store at once, so it is always valid (starts at 0, thresholds rise). Caller commits."""
    try:
        rules.validate_tiers(tiers)
    except LoyaltyError as e:
        raise _fail(e) from e
    await ensure_program(session, store)
    old = await load_tiers(session, store.id)
    before = [tier_out(t) | {"id": str(t.id)} for t in old]
    for t in old:
        await session.delete(t)
    await session.flush()
    rows = [
        LoyaltyTier(store_id=store.id, name=t.name.strip(), min_points=t.min_points, multiplier_bp=t.multiplier_bp)
        for t in rules.sort_tiers(tiers)
    ]
    session.add_all(rows)
    await session.flush()
    audit.record(
        session,
        "loyalty.tiers.saved",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="loyalty_program",
        entity_id=store.id,
        store_id=store.id,
        data={"before": before, "after": [{"name": r.name, "min_points": r.min_points, "multiplier_bp": r.multiplier_bp} for r in rows]},
    )
    return rows


async def list_rewards(session: AsyncSession, store_id: uuid.UUID, *, only_active: bool = False) -> list[LoyaltyReward]:
    q = select(LoyaltyReward).where(LoyaltyReward.store_id == store_id)
    if only_active:
        q = q.where(LoyaltyReward.is_active.is_(True))
    return list((await session.scalars(q.order_by(LoyaltyReward.sort_order, LoyaltyReward.cost_points, LoyaltyReward.created_at))).all())


async def save_reward(
    session: AsyncSession,
    store: Store,
    reward_id: uuid.UUID | None,
    *,
    name: str,
    description: str | None,
    kind: str,
    value: int,
    cost_points: int,
    stock: int | None,
    per_user_limit: int | None,
    sort_order: int,
    is_active: bool,
    actor_id: uuid.UUID,
    actor_type: str,
) -> LoyaltyReward:
    """Create (``reward_id`` None) or change a reward of ONE store; a reward id of another store is simply not found."""
    if not name.strip():
        raise AppError("LOYALTY_BAD_REWARD_NAME", "نام جایزه نامعتبر است.", 400)
    row = None
    if reward_id:
        row = await session.scalar(
            select(LoyaltyReward).where(LoyaltyReward.id == reward_id, LoyaltyReward.store_id == store.id).with_for_update()
        )
        if not row:
            raise NotFound("جایزه")
    try:
        rules.validate_reward(Reward(kind, value, cost_points, stock, row.redeemed_count if row else 0, per_user_limit, is_active))
    except LoyaltyError as e:
        raise _fail(e) from e
    before = reward_out(row) if row else None
    if not row:
        row = LoyaltyReward(store_id=store.id, redeemed_count=0)
        session.add(row)
    row.name, row.description, row.kind, row.value = name.strip(), description, kind, value
    row.cost_points, row.stock, row.per_user_limit = cost_points, stock, per_user_limit
    row.sort_order, row.is_active = sort_order, is_active
    await session.flush()
    audit.record(
        session,
        "loyalty.reward.saved",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="loyalty_reward",
        entity_id=row.id,
        store_id=store.id,
        data={"before": _json(before), "after": _json(reward_out(row))},
    )
    return row


def _json(d: dict | None) -> dict | None:
    return None if d is None else {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in d.items()}


# ---------------------------------------------------------------- the points purse
async def get_account(session: AsyncSession, store_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False) -> LoyaltyAccount:
    """The customer's purse in this store (created on first use). ``lock`` serialises writers on the row."""
    q = select(LoyaltyAccount).where(LoyaltyAccount.store_id == store_id, LoyaltyAccount.user_id == user_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    acc = await session.scalar(q)
    if acc:
        return acc
    try:
        async with session.begin_nested():
            session.add(LoyaltyAccount(store_id=store_id, user_id=user_id, balance=0, lifetime_earned=0, debt=0))
    except IntegrityError:  # concurrent creation
        pass
    return await session.scalar(q)  # type: ignore[return-value]


async def _find_tx(session: AsyncSession, key: str) -> LoyaltyTransaction | None:
    return await session.scalar(select(LoyaltyTransaction).where(LoyaltyTransaction.idempotency_key == key))


async def _post(
    session: AsyncSession,
    acc: LoyaltyAccount,
    *,
    kind: str,
    amount: int,
    key: str,
    order_id: uuid.UUID | None = None,
    reward_id: uuid.UUID | None = None,
    reverses_id: uuid.UUID | None = None,
    memo: str | None = None,
    actor_id: uuid.UUID | None = None,
    debt_recovered: int = 0,
) -> tuple[LoyaltyTransaction, bool]:
    """Append one ledger row and move the balance. Same key => same row, nothing is posted twice. The caller locked ``acc``."""
    existing = await _find_tx(session, key)
    if existing:
        return existing, False
    after = acc.balance + amount
    if after < 0:
        raise AppError("LOYALTY_NOT_ENOUGH_POINTS", "امتیاز شما کافی نیست.", 400)
    tx = LoyaltyTransaction(
        store_id=acc.store_id,
        user_id=acc.user_id,
        account_id=acc.id,
        kind=kind,
        amount=amount,
        balance_after=after,
        order_id=order_id,
        reward_id=reward_id,
        reverses_id=reverses_id,
        idempotency_key=key,
        memo=memo,
        actor_id=actor_id,
        debt_recovered=debt_recovered,
    )
    try:
        async with session.begin_nested():
            session.add(tx)
            await session.flush()
    except IntegrityError:
        existing = await _find_tx(session, key)
        if existing:
            return existing, False
        raise
    acc.balance = after
    return tx, True


async def _earn(
    session: AsyncSession, acc: LoyaltyAccount, points: int, *, kind: str, key: str, order_id: uuid.UUID | None, memo: str
) -> LoyaltyTransaction | None:
    """Credit earned points: an older points debt is settled first, the tier counts everything that was earned."""
    if points <= 0:
        return None
    credited, recovered = rules.offset_with_debt(points, acc.debt)
    tx, created = await _post(session, acc, kind=kind, amount=credited, key=key, order_id=order_id, memo=memo, debt_recovered=recovered)
    if created:
        acc.debt -= recovered
        acc.lifetime_earned += points
    return tx


async def _is_first_order(session: AsyncSession, order: Order) -> bool:
    prior = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.user_id == order.user_id,
            Order.store_id == order.store_id,
            Order.status == OrderStatus.COMPLETED,
            revenue_only(Order.kind),
            Order.total > 0,
            Order.completed_at < order.completed_at,
        )
    )
    return not prior


async def on_order_completed(session: AsyncSession, order_id: uuid.UUID) -> None:
    """Points for a completed order of THIS store's own club: the order points, the first-order bonus and the referrer's bonus."""
    order = await session.get(Order, order_id)
    if not order or not is_revenue(order.kind) or order.total <= 0:
        return
    row = await get_program(session, order.store_id)
    if not row or not row.is_enabled:
        return
    program = program_rules(row)
    tiers = ladder(await load_tiers(session, order.store_id))
    acc = await get_account(session, order.store_id, order.user_id, lock=True)
    tier_before = rules.tier_for(tiers, acc.lifetime_earned)
    earned = 0
    tx = await _earn(
        session,
        acc,
        rules.order_points(order.total, program, rules.multiplier_for(tiers, acc.lifetime_earned)),
        kind="order_earn",
        key=f"loyalty:earn:{order.id}",
        order_id=order.id,
        memo=f"امتیاز سفارش {order.number}",
    )
    earned += (tx.amount + tx.debt_recovered) if tx else 0
    first = program.first_order_bonus > 0 or program.referral_bonus > 0
    if first and order.completed_at and await _is_first_order(session, order):
        bonus = await _earn(
            session,
            acc,
            program.first_order_bonus,
            kind="first_order_bonus",
            key=f"loyalty:first:{order.store_id}:{order.user_id}",
            order_id=order.id,
            memo="پاداش اولین خرید",
        )
        earned += (bonus.amount + bonus.debt_recovered) if bonus else 0
        await _referrer_bonus(session, order, program)
    tier_after = rules.tier_for(tiers, acc.lifetime_earned)
    if earned > 0:
        await _notify_earned(session, order, earned, tier_before, tier_after)


async def _referrer_bonus(session: AsyncSession, order: Order, program: Program) -> None:
    """The person who invited this customer into THIS store gets points once, when the friend completes the first order."""
    if program.referral_bonus <= 0:
        return
    rel = await session.scalar(
        select(ReferralRelationship).where(
            ReferralRelationship.store_id == order.store_id, ReferralRelationship.referred_user_id == order.user_id
        )
    )
    if not rel:
        return
    racc = await get_account(session, order.store_id, rel.referrer_user_id, lock=True)
    await _earn(
        session,
        racc,
        program.referral_bonus,
        kind="referral_bonus",
        key=f"loyalty:referral:{order.store_id}:{order.user_id}",
        order_id=order.id,
        memo="پاداش معرفی دوست",
    )
    await events.emit(
        session,
        events.NOTIFY,
        {
            "user_id": rel.referrer_user_id,
            "store_id": order.store_id,
            "kind": "loyalty",
            "title": "امتیاز معرفی",
            "body": f"{program.referral_bonus:,} امتیاز بابت اولین خرید دوست شما به باشگاه مشتریان اضافه شد.",
        },
        dedup_key=f"notify:loyalty:referral:{order.store_id}:{order.user_id}",
    )


async def _notify_earned(session: AsyncSession, order: Order, earned: int, before: Tier | None, after: Tier | None) -> None:
    body = f"{earned:,} امتیاز بابت سفارش {order.number} به باشگاه مشتریان شما اضافه شد."
    if after and (before is None or after.name != before.name):
        body += f"\nتبریک! به سطح «{after.name}» رسیدید."
    await events.emit_user_notice(
        session, order.user_id, order.store_id, "loyalty", "باشگاه مشتریان", body, dedup_key=f"notify:loyalty:{order.id}"
    )


async def on_order_refunded(session: AsyncSession, order_id: uuid.UUID) -> None:
    """Take back every point this order created (its own points, the first-order bonus, the referrer's bonus).

    What the balance still covers is removed now; what the customer already spent becomes a points debt recovered from his next
    earnings. The tier follows, because the lifetime total shrinks by the whole reversed amount.
    """
    originals = (
        await session.scalars(
            select(LoyaltyTransaction).where(LoyaltyTransaction.order_id == order_id, LoyaltyTransaction.kind.in_(_REVERSIBLE))
        )
    ).all()
    for tx in originals:
        if await _find_tx(session, f"loyalty:reversal:{tx.id}"):
            continue
        acc = await session.scalar(
            select(LoyaltyAccount).where(LoyaltyAccount.id == tx.account_id).with_for_update().execution_options(populate_existing=True)
        )
        if not acc:
            continue
        earned = tx.amount + tx.debt_recovered
        take, owed = rules.split_reversal(earned, acc.balance)
        _, created = await _post(
            session,
            acc,
            kind="reversal",
            amount=-take,
            key=f"loyalty:reversal:{tx.id}",
            order_id=order_id,
            reverses_id=tx.id,
            memo="برگشت امتیاز به‌دلیل استرداد سفارش",
        )
        if created:
            acc.debt += owed
            acc.lifetime_earned = max(0, acc.lifetime_earned - earned)
            await events.emit(
                session,
                events.NOTIFY,
                {
                    "user_id": acc.user_id,
                    "store_id": acc.store_id,
                    "kind": "loyalty",
                    "title": "باشگاه مشتریان",
                    "body": f"{earned:,} امتیاز به‌دلیل استرداد سفارش از باشگاه مشتریان کسر شد.",
                },
                dedup_key=f"notify:loyalty:reversal:{tx.id}",
            )


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
    await events.emit(
        session,
        events.NOTIFY,
        {
            "user_id": user.id,
            "store_id": store.id,
            "kind": "loyalty",
            "title": "جایزه باشگاه مشتریان",
            "body": f"مبلغ {reward.value:,} {store.currency} بابت «{reward.name}» به کیف پول شما اضافه شد.",
        },
        dedup_key=f"notify:loyalty:redeem:{redemption.id}",
    )
    return redemption, True


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


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
    tx, created = await _post(
        session,
        acc,
        kind="admin_grant" if delta > 0 else "admin_deduct",
        amount=delta,
        key=f"loyalty:adjust:{store.id}:{user_id}:{idempotency_key or uuid.uuid4().hex}",
        memo=reason.strip()[:255],
        actor_id=actor_id,
    )
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


# ---------------------------------------------------------------- what customers and owners read
def tx_out(t: LoyaltyTransaction) -> dict:
    return {
        "id": t.id,
        "kind": t.kind,
        "amount": t.amount,
        "balance_after": t.balance_after,
        "order_id": t.order_id,
        "memo": t.memo,
        "created_at": t.created_at,
    }


async def history(
    session: AsyncSession, store_id: uuid.UUID, user_id: uuid.UUID, *, limit: int = 20, before: dt.datetime | None = None
) -> tuple[list[LoyaltyTransaction], bool]:
    """One page of the customer's points entries in this store, newest first. Returns (rows, has_more)."""
    limit = max(1, min(limit, HISTORY_MAX))
    q = select(LoyaltyTransaction).where(LoyaltyTransaction.store_id == store_id, LoyaltyTransaction.user_id == user_id)
    if before:
        q = q.where(LoyaltyTransaction.created_at < before)
    rows = list(
        (await session.scalars(q.order_by(LoyaltyTransaction.created_at.desc(), LoyaltyTransaction.id.desc()).limit(limit + 1))).all()
    )
    return rows[:limit], len(rows) > limit


async def customer_summary(session: AsyncSession, store: Store, user_id: uuid.UUID) -> dict:
    """What the club screen of ONE store shows: standing, the ladder, the rewards he can take and his latest entries."""
    row = await get_program(session, store.id)
    if not row or not row.is_enabled:
        return {"store_id": store.id, "enabled": False}
    tiers_rows = await load_tiers(session, store.id)
    tiers = ladder(tiers_rows)
    acc = await get_account(session, store.id, user_id)
    current = rules.tier_for(tiers, acc.lifetime_earned)
    upcoming, missing = rules.next_tier(tiers, acc.lifetime_earned)
    rewards = await list_rewards(session, store.id, only_active=True)
    recent, more = await history(session, store.id, user_id, limit=10)
    used = dict(
        (
            await session.execute(
                select(LoyaltyRedemption.reward_id, func.count())
                .where(LoyaltyRedemption.store_id == store.id, LoyaltyRedemption.user_id == user_id)
                .group_by(LoyaltyRedemption.reward_id)
            )
        ).all()
    )

    def card(r: LoyaltyReward) -> dict:
        try:
            rules.check_redeem(
                Reward(r.kind, r.value, r.cost_points, r.stock, r.redeemed_count, r.per_user_limit, r.is_active),
                acc.balance,
                int(used.get(r.id, 0)),
            )
            blocked = None
        except LoyaltyError as e:
            blocked = e.code
        return reward_out(r) | {"affordable": acc.balance >= r.cost_points, "available": blocked is None, "blocked_reason": blocked}

    return {
        "store_id": store.id,
        "enabled": True,
        "currency": store.currency,
        "balance": acc.balance,
        "lifetime_earned": acc.lifetime_earned,
        "debt": acc.debt,
        "tier": None if not current else {"name": current.name, "min_points": current.min_points, "multiplier_bp": current.multiplier_bp},
        "next_tier": None if not upcoming else {"name": upcoming.name, "min_points": upcoming.min_points, "points_missing": missing},
        "tiers": [tier_out(t) for t in tiers_rows],
        "program": program_out(row),
        "rewards": [card(r) for r in rewards],
        "history": [tx_out(t) for t in recent],
        "history_more": more,
    }


async def store_summary(session: AsyncSession, store_id: uuid.UUID, *, top: int = 5) -> dict:
    """Numbers of ONE store's club: members, points outstanding, what was issued and redeemed, and the tier distribution."""
    members = await session.scalar(select(func.count()).select_from(LoyaltyAccount).where(LoyaltyAccount.store_id == store_id)) or 0
    outstanding, debt = (
        await session.execute(
            select(func.coalesce(func.sum(LoyaltyAccount.balance), 0), func.coalesce(func.sum(LoyaltyAccount.debt), 0)).where(
                LoyaltyAccount.store_id == store_id
            )
        )
    ).one()
    issued = await session.scalar(
        select(func.coalesce(func.sum(LoyaltyTransaction.amount + LoyaltyTransaction.debt_recovered), 0)).where(
            LoyaltyTransaction.store_id == store_id, LoyaltyTransaction.kind.in_(EARN_KINDS)
        )
    )
    redeemed_points, redeemed_count, paid_value = (
        await session.execute(
            select(
                func.coalesce(func.sum(LoyaltyRedemption.points_spent), 0),
                func.count(),
                func.coalesce(func.sum(LoyaltyRedemption.value), 0),
            ).where(LoyaltyRedemption.store_id == store_id)
        )
    ).one()
    tiers_rows = await load_tiers(session, store_id)
    distribution = []
    for i, t in enumerate(tiers_rows):
        cond = [LoyaltyAccount.store_id == store_id, LoyaltyAccount.lifetime_earned >= t.min_points]
        if i + 1 < len(tiers_rows):
            cond.append(LoyaltyAccount.lifetime_earned < tiers_rows[i + 1].min_points)
        distribution.append(
            {
                "name": t.name,
                "min_points": t.min_points,
                "members": int(await session.scalar(select(func.count()).select_from(LoyaltyAccount).where(*cond)) or 0),
            }
        )
    leaders = (
        await session.execute(
            select(LoyaltyAccount.user_id, LoyaltyAccount.balance, LoyaltyAccount.lifetime_earned)
            .where(LoyaltyAccount.store_id == store_id)
            .order_by(LoyaltyAccount.lifetime_earned.desc())
            .limit(top)
        )
    ).all()
    return {
        "store_id": store_id,
        "members": int(members),
        "points_outstanding": int(outstanding),
        "points_debt": int(debt),
        "points_issued": int(issued or 0),
        "points_redeemed": int(redeemed_points),
        "redemptions": int(redeemed_count),
        "value_paid": int(paid_value),
        "tiers": distribution,
        "top_members": [{"user_id": u, "balance": int(b), "lifetime_earned": int(l)} for u, b, l in leaders],
    }
