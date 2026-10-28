"""Referral attribution and configurable commission plans - one self-contained program PER STORE.

Everything here belongs to ONE store (the main store or one reseller's shop/bot): the referral link, the attribution, the
plan that decides the amount, the wallet the reward lands in and the expense account it is paid from. Nothing crosses stores
(docs/17). Attribution is first-touch inside the store: once a relationship exists there it is never replaced. Plans are
managed by Admin for any store, and by the reseller for his own store. Refunds always create a reversal; if the referrer
spent the reward, the uncovered amount becomes a clawback offset against future commissions of the same store.
"""

import uuid

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events, settings_store
from melorin.core.errors import AppError, NotFound
from melorin.domain.commission import Plan, PlanError, amount_for, offset_with_outstanding, split_reversal, validate_plan
from melorin.domain.order_state import OrderStatus
from melorin.kernel.models.catalog import Product, StoreProduct
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.referral import Commission, CommissionClawback, CommissionRule, ReferralRelationship
from melorin.kernel.models.stores import Store, StoreMembership
from melorin.modules.eventcenter import topics as ec_topics
from melorin.modules.wallet import service as wallet


async def is_store_member(session: AsyncSession, store: Store, user_id: uuid.UUID) -> bool:
    """A person belongs to a store when he has an ACTIVE membership there (or owns it). Blocked members do not count."""
    if store.owner_user_id == user_id:
        return True
    status = await session.scalar(
        select(StoreMembership.status).where(StoreMembership.store_id == store.id, StoreMembership.user_id == user_id)
    )
    return status == "active"


async def has_store_history(session: AsyncSession, store_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """True when the customer already bought (a real, non-test order) in THIS store: he is no longer 'new here'."""
    return bool(
        await session.scalar(select(Order.id).where(Order.user_id == user_id, Order.store_id == store_id, Order.kind != "test").limit(1))
    )


_MAX_CHAIN_DEPTH = 64  # far beyond any real invite chain; only bounds the walk so a corrupted graph can never loop it forever


async def _closes_a_loop(session: AsyncSession, store_id: uuid.UUID, *, referrer_id: uuid.UUID, referred_id: uuid.UUID) -> bool:
    """True when ``referred_id`` already sits ABOVE ``referrer_id`` in this store's invite chain.

    Walks the referrer's own referrer, then that person's referrer, and so on, inside ONE store only (the graphs of different
    stores are independent). The simple two-person loop (A invited B, B tries to invite A) is just the first step of this walk.
    """
    seen = {referrer_id}
    current = referrer_id
    for _ in range(_MAX_CHAIN_DEPTH):
        parent = await session.scalar(
            select(ReferralRelationship.referrer_user_id).where(
                ReferralRelationship.store_id == store_id, ReferralRelationship.referred_user_id == current
            )
        )
        if parent is None:
            return False
        if parent == referred_id:
            return True
        if parent in seen:
            return False  # an old ring that is not about the newcomer: nothing new is closed by this link
        seen.add(parent)
        current = parent
    return False


async def attach(session: AsyncSession, store_id: uuid.UUID, referred: User, referrer: User | None) -> bool:
    """Record ``referrer`` as the first-touch referrer of ``referred`` INSIDE ``store_id``. Returns True when a row was added.

    A referral is valid only inside one store: the store must be active, the referrer must be a member of it (a code from
    another store's customer is not a referral here), the newcomer must not have bought here yet (no hijacking of an existing
    customer) and the first relationship of that store wins. Later links are ignored silently (no oracle for the client).
    """
    if not referrer or referrer.id == referred.id:
        return False
    store = await session.get(Store, store_id)
    if not store or store.status != "active":
        return False
    if not await is_store_member(session, store, referrer.id):
        return False
    exists = await session.scalar(
        select(ReferralRelationship.id).where(
            ReferralRelationship.store_id == store_id, ReferralRelationship.referred_user_id == referred.id
        )
    )
    if exists:
        return False
    if await has_store_history(session, store_id, referred.id):
        return False
    if await _closes_a_loop(session, store_id, referrer_id=referrer.id, referred_id=referred.id):
        return False  # a -> b -> ... -> referrer: making the referrer a's referrer would pay rewards in a circle
    try:  # two sign-ups of the same person racing each other: the unique key lets one win, the other is simply "not attached"
        async with session.begin_nested():
            session.add(ReferralRelationship(store_id=store_id, referrer_user_id=referrer.id, referred_user_id=referred.id))
            await session.flush()
    except IntegrityError:
        return False
    await events.emit(
        session,
        events.EVENT_CENTER,
        {"store_id": store_id, "topic": ec_topics.AFFILIATE, "text": "👥 معرف جدید ثبت شد\nیک کاربر با لینک معرفی ثبت‌نام کرد."},
        dedup_key=f"ec:affiliate:attach:{store_id}:{referred.id}",
    )
    return True


async def _plan(session: AsyncSession, order: Order, kind: str) -> Plan | None:
    rows = (
        await session.scalars(
            select(CommissionRule).where(
                CommissionRule.store_id == order.store_id, CommissionRule.kind == kind, CommissionRule.is_active.is_(True)
            )
        )
    ).all()
    specific = next((r for r in rows if r.product_id == order.product_id), None)
    rule = specific or next((r for r in rows if r.product_id is None), None)
    if rule:
        return Plan(kind=rule.kind, model=rule.model, value=rule.value, max_amount=rule.max_amount, active=rule.is_active)
    store = await session.get(Store, order.store_id)
    if not store or store.kind != "main":
        return None  # a reseller store pays only what ITS owner configured; the main store's defaults never leak into it
    # Backward-compatible global settings: the MAIN store's default when Admin has not defined a rule for it.
    if kind == "signup_reward":
        return Plan(kind, "fixed", int(await settings_store.get(session, "referral.signup_reward") or 0))
    return Plan(kind, "percent", int(await settings_store.get(session, "referral.commission_bp") or 0))


async def on_order_completed(session: AsyncSession, order_id: uuid.UUID) -> None:
    order = await session.get(Order, order_id)
    if not order or order.kind == "test" or order.total <= 0:
        return
    # Store isolation (docs/17): the relationship is looked up INSIDE the order's own store. A referral made in another store
    # never pays here and never charges this store's referral-expense account; this store's own relationship (if any) is the one used.
    rel = await session.scalar(
        select(ReferralRelationship).where(
            ReferralRelationship.referred_user_id == order.user_id, ReferralRelationship.store_id == order.store_id
        )
    )
    if not rel:
        return
    prior = (
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.user_id == order.user_id,
                # "First purchase" is counted inside the referral's own store: a purchase made earlier in another store must not
                # downgrade the signup reward of this store to a plain commission.
                Order.store_id == order.store_id,
                Order.status == OrderStatus.COMPLETED,
                Order.kind != "test",
                Order.total > 0,
                Order.completed_at < order.completed_at,
            )
        )
        or 0
    )
    # The reward is one per customer per store (unique key). If it was already granted - even when that first order was later
    # refunded and so no longer counts as "completed" - every further order pays the commission plan, never a second reward.
    reward_granted = await session.scalar(
        select(Commission.id).where(
            Commission.store_id == order.store_id, Commission.referred_user_id == order.user_id, Commission.kind == "signup_reward"
        )
    )
    kind = "signup_reward" if prior == 0 and not reward_granted else "commission"
    plan = await _plan(session, order, kind)
    gross = amount_for(plan, order.total)
    if gross <= 0 or await session.scalar(select(Commission.id).where(Commission.order_id == order.id, Commission.kind == kind)):
        return
    w = await wallet.get_wallet(session, rel.referrer_user_id, order.store_id, currency=order.currency)
    claw = await session.scalar(
        select(CommissionClawback)
        .where(
            CommissionClawback.referrer_user_id == rel.referrer_user_id,
            CommissionClawback.store_id == order.store_id,
            CommissionClawback.currency == order.currency,
        )
        .with_for_update()
    )
    outstanding = claw.outstanding if claw else 0
    payout, recovered = offset_with_outstanding(gross, outstanding)
    if recovered and claw:
        claw.outstanding -= recovered
    tx = None
    if payout:
        tx, _ = await wallet.post(
            session,
            kind="referral_" + kind,
            key=f"referral:{order.id}:{kind}",
            currency=order.currency,
            store_id=order.store_id,
            order_id=order.id,
            postings=[wallet.Posting(payout, wallet=w), wallet.Posting(-payout, account=wallet.acc_referral_expense(order.store_id))],
            memo="پاداش معرفی" if kind == "signup_reward" else "کمیسیون معرفی",
        )
    session.add(
        Commission(
            store_id=order.store_id,
            order_id=order.id,
            referrer_user_id=rel.referrer_user_id,
            referred_user_id=order.user_id,
            kind=kind,
            amount=gross,
            offset_amount=recovered,
            status="credited",
            ledger_tx_id=tx.id if tx else None,
            currency=order.currency,
        )
    )
    if recovered:
        audit.record(
            session,
            "commission.clawback_offset",
            actor_type="system",
            entity_type="commission",
            entity_id=order.id,
            store_id=order.store_id,
            data={"recovered": recovered, "gross": gross},
        )
    await events.emit(
        session,
        events.NOTIFY,
        {
            "user_id": rel.referrer_user_id,
            "store_id": order.store_id,
            "kind": "referral",
            "title": "پاداش معرفی",
            "body": f"مبلغ {payout:,} به کیف پول شما اضافه شد.",
        },
        dedup_key=f"notify:referral:{order.id}:{kind}",
    )
    head = "🎁 پاداش اولین خرید معرف" if kind == "signup_reward" else "🤝 کمیسیون معرف"
    text = f"{head}\nسفارش: {order.number}\nمبلغ: {gross:,} {order.currency}"
    if recovered:
        text += f"\nکسر بدهی قبلی معرف: {recovered:,}"
    await events.emit(
        session,
        events.EVENT_CENTER,
        {"store_id": order.store_id, "topic": ec_topics.AFFILIATE, "text": text},
        dedup_key=f"ec:affiliate:{order.id}:{kind}",
    )


async def on_order_refunded(session: AsyncSession, order_id: uuid.UUID) -> None:
    rows = (
        await session.scalars(select(Commission).where(Commission.order_id == order_id, Commission.status == "credited").with_for_update())
    ).all()
    for c in rows:
        if c.ledger_tx_id:
            w = await wallet.get_wallet(session, c.referrer_user_id, c.store_id, currency=c.currency or "IRT")
            await wallet.lock_wallets(session, [w])
            take, outstanding = split_reversal(c.amount - c.offset_amount, w.balance)
            if take:
                await wallet.post(
                    session,
                    kind="commission_reversal",
                    key=f"commission_reversal:{c.id}",
                    currency=w.currency,
                    store_id=c.store_id,
                    order_id=order_id,
                    postings=[
                        wallet.Posting(-take, wallet=w, min_balance=0),
                        wallet.Posting(take, account=wallet.acc_referral_expense(c.store_id)),
                    ],
                    memo="برگشت کمیسیون به‌دلیل استرداد",
                )
            if outstanding:
                claw = await session.scalar(
                    select(CommissionClawback)
                    .where(
                        CommissionClawback.referrer_user_id == c.referrer_user_id,
                        CommissionClawback.store_id == c.store_id,
                        CommissionClawback.currency == w.currency,
                    )
                    .with_for_update()
                )
                if not claw:
                    claw = CommissionClawback(referrer_user_id=c.referrer_user_id, store_id=c.store_id, currency=w.currency, outstanding=0)
                    session.add(claw)
                claw.outstanding += outstanding
            c.reversed_amount = take + outstanding
            c.status = "reversed"
            order = await session.get(Order, order_id)
            text = f"↩️ کمیسیون معرف به‌دلیل استرداد برگشت خورد\nسفارش: {order.number if order else '-'}\nبرگشت‌شده: {take:,} {c.currency or ''}".rstrip()
            if outstanding:
                text += f"\nبدهی باقی‌مانده معرف: {outstanding:,}"
            await events.emit(
                session,
                events.EVENT_CENTER,
                {"store_id": c.store_id, "topic": ec_topics.AFFILIATE, "text": text},
                dedup_key=f"ec:affiliate:reversal:{c.id}",
            )


async def earnings(session: AsyncSession, referrer_id: uuid.UUID, store_id: uuid.UUID) -> dict:
    """What ``referrer_id`` really earned in ONE store: summed in the database over ALL his commissions there.

    The customer screens list only the latest commissions, so adding up that list under-reports an active referrer; this is
    the single source of the number. A reversed commission keeps only what was not taken back (normally nothing)."""
    net = Commission.amount - Commission.offset_amount - case((Commission.status == "reversed", Commission.reversed_amount), else_=0)
    total, count = (
        await session.execute(
            select(func.coalesce(func.sum(net), 0), func.count()).where(
                Commission.referrer_user_id == referrer_id, Commission.store_id == store_id
            )
        )
    ).one()
    return {"earned": max(0, int(total)), "commissions_total": int(count)}


# ---------------------------------------------------------------- plan management (one store at a time)
def rule_out(r: CommissionRule) -> dict:
    return {
        "id": r.id,
        "store_id": r.store_id,
        "product_id": r.product_id,
        "kind": r.kind,
        "model": r.model,
        "value": r.value,
        "max_amount": r.max_amount,
        "is_active": r.is_active,
    }


def _audit_view(r: CommissionRule) -> dict:
    """``rule_out`` with JSON-safe ids (the audit log stores JSON)."""
    return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in rule_out(r).items()}


async def list_rules(session: AsyncSession, store_id: uuid.UUID) -> list[CommissionRule]:
    q = select(CommissionRule).where(CommissionRule.store_id == store_id).order_by(CommissionRule.kind, CommissionRule.created_at)
    return list((await session.scalars(q)).all())


async def _check_product(session: AsyncSession, store: Store, product_id: uuid.UUID) -> None:
    """A product-specific plan must be about a product this store really sells."""
    if not await session.get(Product, product_id):
        raise NotFound("محصول")
    if store.kind == "reseller":
        offered = await session.scalar(
            select(StoreProduct.id).where(
                StoreProduct.store_id == store.id, StoreProduct.product_id == product_id, StoreProduct.is_enabled.is_(True)
            )
        )
        if not offered:
            raise AppError("REFERRAL_PRODUCT_NOT_IN_STORE", "این محصول در این فروشگاه فعال نیست.", 400)


async def upsert_rule(
    session: AsyncSession,
    store: Store,
    *,
    product_id: uuid.UUID | None,
    kind: str,
    model: str,
    value: int,
    max_amount: int | None,
    is_active: bool,
    actor_id: uuid.UUID,
    actor_type: str,
) -> CommissionRule:
    """Create or change the plan of ONE store. The caller has already proven it may act on ``store`` (Admin, or the owner
    through the owner plane); nothing here reads or writes another store's plans. The caller commits."""
    try:
        validate_plan(Plan(kind=kind, model=model, value=value, max_amount=max_amount, active=is_active))
    except PlanError as e:
        raise AppError(e.code, e.message, 400) from e
    if product_id:
        await _check_product(session, store, product_id)
    row = await session.scalar(
        select(CommissionRule).where(
            CommissionRule.store_id == store.id,
            CommissionRule.product_id.is_(None) if product_id is None else CommissionRule.product_id == product_id,
            CommissionRule.kind == kind,
        )
    )
    before = _audit_view(row) if row else None
    if not row:
        row = CommissionRule(store_id=store.id, product_id=product_id, kind=kind)
        session.add(row)
    row.model, row.value, row.max_amount, row.is_active = model, value, max_amount, is_active
    await session.flush()
    audit.record(
        session,
        "referral.rule.saved",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="commission_rule",
        entity_id=row.id,
        store_id=store.id,
        data={"before": before, "after": _audit_view(row)},
    )
    return row


async def program_for(session: AsyncSession, store: Store) -> dict:
    """What a customer of THIS store earns by inviting friends, in plain numbers (no rule = no programme)."""
    rows = [r for r in await list_rules(session, store.id) if r.is_active and r.product_id is None]
    default = {r.kind: r for r in rows}
    out: dict = {"enabled": False, "currency": store.currency}
    for kind in ("signup_reward", "commission"):
        r = default.get(kind)
        if r and r.value > 0:
            out[kind] = {"model": r.model, "value": r.value, "max_amount": r.max_amount}
            out["enabled"] = True
    if store.kind == "main" and not out["enabled"]:  # legacy global defaults still apply to the main store only
        reward = int(await settings_store.get(session, "referral.signup_reward") or 0)
        bp = int(await settings_store.get(session, "referral.commission_bp") or 0)
        if reward > 0:
            out["signup_reward"] = {"model": "fixed", "value": reward, "max_amount": None}
        if bp > 0:
            out["commission"] = {"model": "percent", "value": bp, "max_amount": None}
        out["enabled"] = reward > 0 or bp > 0
    out["has_product_rules"] = any(r.is_active and r.product_id is not None for r in await list_rules(session, store.id))
    return out


async def store_summary(session: AsyncSession, store_id: uuid.UUID, *, top: int = 5) -> dict:
    """Numbers of ONE store's programme: members invited, what was paid, reversed and is still owed back."""
    invited = (
        await session.scalar(select(func.count()).select_from(ReferralRelationship).where(ReferralRelationship.store_id == store_id)) or 0
    )
    referrers = (
        await session.scalar(
            select(func.count(func.distinct(ReferralRelationship.referrer_user_id))).where(ReferralRelationship.store_id == store_id)
        )
        or 0
    )
    paid_rows = (
        await session.execute(
            select(
                Commission.kind,
                Commission.status,
                func.count(),
                func.coalesce(func.sum(Commission.amount), 0),
                func.coalesce(func.sum(Commission.offset_amount), 0),
                func.coalesce(func.sum(Commission.reversed_amount), 0),
            )
            .where(Commission.store_id == store_id)
            .group_by(Commission.kind, Commission.status)
        )
    ).all()
    kinds: dict[str, dict] = {}
    total_paid = total_reversed = 0
    for kind, status, n, amount, offset, reversed_ in paid_rows:
        k = kinds.setdefault(kind, {"count": 0, "gross": 0, "reversed": 0})
        k["count"] += n
        k["gross"] += int(amount)
        k["reversed"] += int(reversed_) if status == "reversed" else 0
        total_paid += int(amount) - int(offset)
        total_reversed += int(reversed_) if status == "reversed" else 0
    outstanding = await session.scalar(
        select(func.coalesce(func.sum(CommissionClawback.outstanding), 0)).where(CommissionClawback.store_id == store_id)
    )
    leaders = (
        await session.execute(
            select(Commission.referrer_user_id, func.count(), func.coalesce(func.sum(Commission.amount - Commission.offset_amount), 0))
            .where(Commission.store_id == store_id, Commission.status == "credited")
            .group_by(Commission.referrer_user_id)
            .order_by(func.sum(Commission.amount - Commission.offset_amount).desc())
            .limit(top)
        )
    ).all()
    return {
        "store_id": store_id,
        "invited": invited,
        "referrers": referrers,
        "paid_out": total_paid,
        "reversed": total_reversed,
        "outstanding_clawback": int(outstanding or 0),
        "by_kind": kinds,
        "top_referrers": [{"user_id": uid, "rewards": int(n), "paid": int(paid)} for uid, n, paid in leaders],
    }
