"""Customer loyalty club service (docs/22): earning, refunds, points debt, redeeming, admin adjustments, store isolation."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func, select

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain.loyalty import Tier
from melorin.kernel.models.loyalty import LoyaltyAccount, LoyaltyRedemption, LoyaltyReward, LoyaltyTier, LoyaltyTransaction
from melorin.kernel.models.referral import ReferralRelationship
from melorin.kernel.models.stores import StoreMembership
from melorin.kernel.models.system import AuditEvent, OutboxEvent
from melorin.kernel.models.wallet import LedgerEntry, Wallet
from melorin.modules.loyalty import service as club


# ------------------------------------------------------------------ helpers
async def _join(s, store, *users):
    for u in users:
        s.add(StoreMembership(store_id=store.id, user_id=u.id, role="customer"))
    await s.flush()


async def _world(s, *, enabled=True, **program):
    """a reseller store with a running club, one customer who joined it, a product and an admin actor."""
    owner = await make_user(s)
    store = await make_store(s, kind="reseller", owner=owner, slug="club-shop")
    customer, admin = await make_user(s), await make_user(s, super_admin=True)
    await _join(s, store, customer)
    product = await make_product(s)
    cfg = dict(earn_unit=1000, points_per_unit=1, max_points_per_order=None, first_order_bonus=0, referral_bonus=0) | program
    await club.upsert_program(s, store, enabled=enabled, actor_id=admin.id, actor_type="admin", **cfg)
    await s.commit()
    return store, customer, product, admin


_clock = [0]


async def _complete(s, user, store, product, *, total=10_000, kind="purchase"):
    o = await make_order(s, user=user, store=store, product=product, total=total, status="completed")
    o.kind = o.kind if kind == "purchase" else kind
    _clock[0] += 1  # strictly increasing completion times, so "first order" is unambiguous
    o.completed_at = utcnow() + dt.timedelta(seconds=_clock[0])
    await s.commit()
    return o


async def _acc(s, store, user) -> LoyaltyAccount:
    return await club.get_account(s, store.id, user.id)


async def _txs(s, store, user, kind=None):
    q = select(LoyaltyTransaction).where(LoyaltyTransaction.store_id == store.id, LoyaltyTransaction.user_id == user.id)
    if kind:
        q = q.where(LoyaltyTransaction.kind == kind)
    return list((await s.scalars(q.order_by(LoyaltyTransaction.created_at, LoyaltyTransaction.id))).all())


async def _reward(s, store, admin, **kw):
    cfg = dict(
        name="credit",
        description=None,
        kind="wallet_credit",
        value=5_000,
        cost_points=100,
        stock=None,
        per_user_limit=None,
        sort_order=0,
        is_active=True,
    )
    r = await club.save_reward(s, store, None, actor_id=admin.id, actor_type="admin", **(cfg | kw))
    await s.commit()
    return r


# ------------------------------------------------------------------ a club starts disabled with the default ladder
async def test_a_new_program_starts_disabled_with_the_default_ladder():
    async with open_session() as s:
        store = await make_store(s, kind="reseller", owner=await make_user(s))
        row = await club.ensure_program(s, store)
        assert row.is_enabled is False
        names = [t.name for t in await club.load_tiers(s, store.id)]
        assert len(names) == 4
        assert (await club.ensure_program(s, store)).id == row.id  # idempotent, no second ladder
        assert (await s.scalar(select(func.count()).select_from(LoyaltyTier))) == 4


async def test_a_disabled_club_earns_nothing():
    async with open_session() as s:
        store, customer, product, _ = await _world(s, enabled=False)
        order = await _complete(s, customer, store, product)
        await club.on_order_completed(s, order.id)
        assert await _txs(s, store, customer) == []


# ------------------------------------------------------------------ earning
async def test_a_completed_order_earns_points_on_the_net_paid_amount():
    async with open_session() as s:
        store, customer, product, _ = await _world(s)
        order = await _complete(s, customer, store, product, total=12_999)
        await club.on_order_completed(s, order.id)
        acc = await _acc(s, store, customer)
        assert (acc.balance, acc.lifetime_earned, acc.debt) == (12, 12, 0)
        (tx,) = await _txs(s, store, customer)
        assert (tx.kind, tx.amount, tx.balance_after, tx.order_id) == ("order_earn", 12, 12, order.id)


async def test_completing_the_same_order_twice_pays_once():
    async with open_session() as s:
        store, customer, product, _ = await _world(s)
        order = await _complete(s, customer, store, product)
        await club.on_order_completed(s, order.id)
        await club.on_order_completed(s, order.id)
        await s.commit()
        assert (await _acc(s, store, customer)).balance == 10
        assert len(await _txs(s, store, customer)) == 1


@pytest.mark.parametrize("kind", ["test"])
async def test_test_orders_and_free_orders_earn_nothing(kind):
    async with open_session() as s:
        store, customer, product, _ = await _world(s)
        test_order = await _complete(s, customer, store, product, kind=kind)
        free_order = await _complete(s, customer, store, product, total=0)
        for o in (test_order, free_order):
            await club.on_order_completed(s, o.id)
        assert await _txs(s, store, customer) == []


async def test_the_tier_multiplier_applies_to_later_orders_only():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        await club.replace_tiers(s, store, [Tier("a", 0, 10_000), Tier("b", 10, 20_000)], actor_id=admin.id, actor_type="admin")
        await s.commit()
        first = await _complete(s, customer, store, product, total=10_000)
        await club.on_order_completed(s, first.id)  # 10 points at 1.0x -> reaches tier b
        second = await _complete(s, customer, store, product, total=10_000)
        await club.on_order_completed(s, second.id)  # 10 points at 2.0x
        assert [t.amount for t in await _txs(s, store, customer)] == [10, 20]
        assert (await _acc(s, store, customer)).lifetime_earned == 30


async def test_the_per_order_cap_limits_the_points():
    async with open_session() as s:
        store, customer, product, _ = await _world(s, max_points_per_order=5)
        order = await _complete(s, customer, store, product, total=100_000)
        await club.on_order_completed(s, order.id)
        assert (await _acc(s, store, customer)).balance == 5


async def test_each_store_has_its_own_club_and_purse():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        other_owner = await make_user(s)
        other = await make_store(s, kind="reseller", owner=other_owner, slug="other-shop")
        await _join(s, other, customer)
        await club.upsert_program(
            s,
            other,
            enabled=True,
            earn_unit=1000,
            points_per_unit=5,
            max_points_per_order=None,
            first_order_bonus=0,
            referral_bonus=0,
            actor_id=admin.id,
            actor_type="admin",
        )
        await s.commit()
        a, b = await _complete(s, customer, store, product), await _complete(s, customer, other, product)
        await club.on_order_completed(s, a.id)
        await club.on_order_completed(s, b.id)
        assert (await _acc(s, store, customer)).balance == 10
        assert (await _acc(s, other, customer)).balance == 50


# ------------------------------------------------------------------ bonuses
async def test_the_first_order_bonus_is_paid_once_and_only_to_a_new_customer():
    async with open_session() as s:
        store, customer, product, _ = await _world(s, first_order_bonus=50)
        first = await _complete(s, customer, store, product)
        await club.on_order_completed(s, first.id)
        second = await _complete(s, customer, store, product)
        await club.on_order_completed(s, second.id)
        assert [t.kind for t in await _txs(s, store, customer)] == ["order_earn", "first_order_bonus", "order_earn"]
        assert (await _acc(s, store, customer)).balance == 10 + 50 + 10


async def test_a_customer_who_bought_before_the_club_started_gets_no_first_order_bonus():
    async with open_session() as s:
        store, customer, product, _ = await _world(s, first_order_bonus=50)
        await _complete(s, customer, store, product)  # bought earlier, nobody called the club for it
        later = await _complete(s, customer, store, product)
        await club.on_order_completed(s, later.id)
        assert [t.kind for t in await _txs(s, store, customer)] == ["order_earn"]


async def test_the_referrer_gets_points_when_the_invited_friend_completes_the_first_order():
    async with open_session() as s:
        store, friend, product, _ = await _world(s, referral_bonus=200)
        referrer = await make_user(s)
        await _join(s, store, referrer)
        s.add(ReferralRelationship(store_id=store.id, referrer_user_id=referrer.id, referred_user_id=friend.id))
        await s.commit()
        first, second = await _complete(s, friend, store, product), None
        await club.on_order_completed(s, first.id)
        second = await _complete(s, friend, store, product)
        await club.on_order_completed(s, second.id)
        assert (await _acc(s, store, referrer)).balance == 200  # once, not per order
        (tx,) = await _txs(s, store, referrer)
        assert (tx.kind, tx.order_id) == ("referral_bonus", first.id)


async def test_no_referral_bonus_without_a_relationship_in_this_store():
    async with open_session() as s:
        store, friend, product, _ = await _world(s, referral_bonus=200)
        stranger = await make_user(s)
        order = await _complete(s, friend, store, product)
        await club.on_order_completed(s, order.id)
        assert await _txs(s, store, stranger) == []


# ------------------------------------------------------------------ refunds
async def test_a_refund_takes_the_points_of_that_order_back_and_lowers_the_tier():
    async with open_session() as s:
        store, customer, product, admin = await _world(s, first_order_bonus=50)
        await club.replace_tiers(s, store, [Tier("a", 0, 10_000), Tier("b", 60, 15_000)], actor_id=admin.id, actor_type="admin")
        await s.commit()
        order = await _complete(s, customer, store, product)
        await club.on_order_completed(s, order.id)
        assert (await _acc(s, store, customer)).lifetime_earned == 60
        await club.on_order_refunded(s, order.id)
        await club.on_order_refunded(s, order.id)  # a retried event changes nothing
        await s.commit()
        acc = await _acc(s, store, customer)
        assert (acc.balance, acc.lifetime_earned, acc.debt) == (0, 0, 0)
        summary = await club.customer_summary(s, store, customer.id)
        assert summary["tier"]["name"] == "a"
        assert len(await _txs(s, store, customer, "reversal")) == 2  # the order points and the first-order bonus


async def test_spent_points_become_a_debt_that_the_next_earnings_settle_first():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        reward = await _reward(s, store, admin, cost_points=80)
        order = await _complete(s, customer, store, product, total=100_000)
        await club.on_order_completed(s, order.id)  # 100 points
        user = await s.get(type(customer), customer.id)
        await club.redeem(s, store, user, reward.id, idempotency_key="r1")  # spends 80 -> 20 left
        await s.commit()
        await club.on_order_refunded(s, order.id)
        await s.commit()
        acc = await _acc(s, store, customer)
        assert (acc.balance, acc.debt, acc.lifetime_earned) == (0, 80, 0)  # the balance never goes negative
        nxt = await _complete(s, customer, store, product, total=50_000)
        await club.on_order_completed(s, nxt.id)  # 50 points: 50 go to the debt
        await s.commit()
        acc = await _acc(s, store, customer)
        assert (acc.balance, acc.debt, acc.lifetime_earned) == (0, 30, 50)
        (tx,) = (await _txs(s, store, customer, "order_earn"))[-1:]
        assert (tx.amount, tx.debt_recovered) == (0, 50)


# ------------------------------------------------------------------ redeeming
async def test_redeeming_spends_points_and_credits_the_store_wallet_through_the_ledger():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        reward = await _reward(s, store, admin, value=7_000, cost_points=100)
        order = await _complete(s, customer, store, product, total=150_000)
        await club.on_order_completed(s, order.id)
        redemption, created = await club.redeem(s, store, customer, reward.id, idempotency_key="k1")
        await s.commit()
        assert created is True
        acc = await _acc(s, store, customer)
        assert acc.balance == 50
        assert (redemption.points_spent, redemption.value, redemption.currency) == (100, 7_000, store.currency)
        w = await s.scalar(select(Wallet).where(Wallet.user_id == customer.id, Wallet.store_id == store.id))
        assert w.balance == 7_000
        entries = (await s.scalars(select(LedgerEntry).where(LedgerEntry.transaction_id == redemption.ledger_tx_id))).all()
        assert sum(e.amount for e in entries) == 0  # double-entry: the club's expense account paid it
        assert {e.account for e in entries} >= {f"store:{store.id}:loyalty_expense"}
        refreshed = await s.get(LoyaltyReward, reward.id)
        assert refreshed.redeemed_count == 1


async def test_the_same_redeem_retried_with_one_key_spends_once():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        reward = await _reward(s, store, admin, cost_points=10)
        await club.on_order_completed(s, (await _complete(s, customer, store, product, total=100_000)).id)
        first, c1 = await club.redeem(s, store, customer, reward.id, idempotency_key="same")
        second, c2 = await club.redeem(s, store, customer, reward.id, idempotency_key="same")
        await s.commit()
        assert (c1, c2) == (True, False) and first.id == second.id
        assert (await _acc(s, store, customer)).balance == 90
        w = await s.scalar(select(Wallet).where(Wallet.user_id == customer.id, Wallet.store_id == store.id))
        assert w.balance == 5_000


async def test_a_key_cannot_be_reused_for_another_reward():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        r1, r2 = await _reward(s, store, admin, name="a", cost_points=10), await _reward(s, store, admin, name="b", cost_points=20)
        await club.on_order_completed(s, (await _complete(s, customer, store, product, total=100_000)).id)
        await club.redeem(s, store, customer, r1.id, idempotency_key="k")
        with pytest.raises(AppError) as exc:
            await club.redeem(s, store, customer, r2.id, idempotency_key="k")
        assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.parametrize(
    ("reward_kw", "code"),
    [
        (dict(cost_points=1_000), "LOYALTY_NOT_ENOUGH_POINTS"),
        (dict(stock=0), "LOYALTY_REWARD_SOLD_OUT"),
        (dict(is_active=False), "LOYALTY_REWARD_INACTIVE"),
    ],
)
async def test_a_reward_the_customer_cannot_take_never_reaches_the_ledger(reward_kw, code):
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        reward = await _reward(s, store, admin, **reward_kw)
        await club.on_order_completed(s, (await _complete(s, customer, store, product, total=100_000)).id)
        with pytest.raises(AppError) as exc:
            await club.redeem(s, store, customer, reward.id)
        assert exc.value.code == code
        assert (await _acc(s, store, customer)).balance == 100
        assert (await s.scalar(select(func.count()).select_from(LoyaltyRedemption))) == 0


async def test_the_per_customer_limit_is_enforced():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        reward = await _reward(s, store, admin, cost_points=10, per_user_limit=1)
        await club.on_order_completed(s, (await _complete(s, customer, store, product, total=100_000)).id)
        await club.redeem(s, store, customer, reward.id, idempotency_key="a")
        with pytest.raises(AppError) as exc:
            await club.redeem(s, store, customer, reward.id, idempotency_key="b")
        assert exc.value.code == "LOYALTY_REWARD_LIMIT"


async def test_stock_runs_out_after_the_last_unit():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        reward = await _reward(s, store, admin, cost_points=10, stock=1)
        await club.on_order_completed(s, (await _complete(s, customer, store, product, total=100_000)).id)
        await club.redeem(s, store, customer, reward.id, idempotency_key="a")
        with pytest.raises(AppError) as exc:
            await club.redeem(s, store, customer, reward.id, idempotency_key="b")
        assert exc.value.code == "LOYALTY_REWARD_SOLD_OUT"


async def test_a_reward_of_another_store_is_not_found_and_a_disabled_club_refuses():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        other = await make_store(s, kind="reseller", owner=await make_user(s), slug="x-shop")
        await club.upsert_program(
            s,
            other,
            enabled=True,
            earn_unit=1000,
            points_per_unit=1,
            max_points_per_order=None,
            first_order_bonus=0,
            referral_bonus=0,
            actor_id=admin.id,
            actor_type="admin",
        )
        foreign = await _reward(s, other, admin)
        await club.on_order_completed(s, (await _complete(s, customer, store, product, total=100_000)).id)
        with pytest.raises(AppError) as nf:
            await club.redeem(s, store, customer, foreign.id)
        assert nf.value.code == "NOT_FOUND"
        await club.upsert_program(
            s,
            store,
            enabled=False,
            earn_unit=1000,
            points_per_unit=1,
            max_points_per_order=None,
            first_order_bonus=0,
            referral_bonus=0,
            actor_id=admin.id,
            actor_type="admin",
        )
        with pytest.raises(AppError) as exc:
            await club.redeem(s, store, customer, foreign.id)
        assert exc.value.code == "LOYALTY_DISABLED"


# ------------------------------------------------------------------ admin adjustments
async def test_grant_and_deduct_move_the_balance_and_leave_an_audit_trail():
    async with open_session() as s:
        store, customer, _, admin = await _world(s)
        await club.adjust(s, store, customer.id, 120, reason="gift", actor_id=admin.id, actor_type="admin")
        await club.adjust(s, store, customer.id, -20, reason="correction", actor_id=admin.id, actor_type="admin")
        await s.commit()
        acc = await _acc(s, store, customer)
        assert (acc.balance, acc.lifetime_earned) == (100, 120)  # a deduction never lowers the tier
        actions = (await s.scalars(select(AuditEvent.action).where(AuditEvent.action == "loyalty.points.adjusted"))).all()
        assert len(actions) == 2


async def test_adjustments_are_validated():
    async with open_session() as s:
        store, customer, _, admin = await _world(s)
        stranger = await make_user(s)
        for kwargs, code in [
            (dict(delta=0, reason="x"), "LOYALTY_BAD_ADJUSTMENT"),
            (dict(delta=5, reason="  "), "LOYALTY_REASON_REQUIRED"),
            (dict(delta=-5, reason="x"), "LOYALTY_NOT_ENOUGH_POINTS"),
        ]:
            with pytest.raises(AppError) as exc:
                await club.adjust(s, store, customer.id, kwargs["delta"], reason=kwargs["reason"], actor_id=admin.id, actor_type="admin")
            assert exc.value.code == code
        with pytest.raises(AppError) as nf:
            await club.adjust(s, store, stranger.id, 5, reason="x", actor_id=admin.id, actor_type="admin")
        assert nf.value.code == "NOT_FOUND"


# ------------------------------------------------------------------ definitions
async def test_a_bad_program_or_ladder_or_reward_is_rejected_with_its_code():
    async with open_session() as s:
        store, _, _, admin = await _world(s)
        with pytest.raises(AppError) as exc:
            await club.upsert_program(
                s,
                store,
                enabled=True,
                earn_unit=0,
                points_per_unit=1,
                max_points_per_order=None,
                first_order_bonus=0,
                referral_bonus=0,
                actor_id=admin.id,
                actor_type="admin",
            )
        assert exc.value.code == "LOYALTY_BAD_EARN_UNIT"
        with pytest.raises(AppError) as exc:
            await club.replace_tiers(s, store, [Tier("a", 5)], actor_id=admin.id, actor_type="admin")
        assert exc.value.code == "LOYALTY_TIERS_START"
        assert len(await club.load_tiers(s, store.id)) == 4  # a rejected ladder leaves the old one untouched
        with pytest.raises(AppError) as exc:
            await _reward(s, store, admin, cost_points=0)
        assert exc.value.code == "LOYALTY_BAD_REWARD_COST"


async def test_a_reward_can_be_changed_only_inside_its_own_store():
    async with open_session() as s:
        store, _, _, admin = await _world(s)
        other = await make_store(s, kind="reseller", owner=await make_user(s), slug="y-shop")
        reward = await _reward(s, store, admin)
        with pytest.raises(AppError) as nf:
            await club.save_reward(
                s,
                other,
                reward.id,
                name="hijack",
                description=None,
                kind="wallet_credit",
                value=1,
                cost_points=1,
                stock=None,
                per_user_limit=None,
                sort_order=0,
                is_active=True,
                actor_id=admin.id,
                actor_type="admin",
            )
        assert nf.value.code == "NOT_FOUND"
        updated = await club.save_reward(
            s,
            store,
            reward.id,
            name="renamed",
            description="d",
            kind="wallet_credit",
            value=9_000,
            cost_points=150,
            stock=5,
            per_user_limit=2,
            sort_order=3,
            is_active=True,
            actor_id=admin.id,
            actor_type="admin",
        )
        assert (updated.id, updated.name, updated.value, updated.cost_points) == (reward.id, "renamed", 9_000, 150)


# ------------------------------------------------------------------ what people read
async def test_the_customer_summary_shows_standing_ladder_rewards_and_history():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        await _reward(s, store, admin, name="cheap", cost_points=5)
        await _reward(s, store, admin, name="dear", cost_points=5_000)
        await club.on_order_completed(s, (await _complete(s, customer, store, product, total=20_000)).id)
        summary = await club.customer_summary(s, store, customer.id)
        assert summary["enabled"] is True
        assert (summary["balance"], summary["lifetime_earned"]) == (20, 20)
        assert summary["tier"]["multiplier_bp"] == 10_000
        assert summary["next_tier"]["points_missing"] == 480
        by_name = {r["name"]: r for r in summary["rewards"]}
        assert by_name["cheap"]["available"] is True and by_name["dear"]["blocked_reason"] == "LOYALTY_NOT_ENOUGH_POINTS"
        assert [h["kind"] for h in summary["history"]] == ["order_earn"]


async def test_the_summary_of_a_store_without_a_club_says_so():
    async with open_session() as s:
        store = await make_store(s, kind="reseller", owner=await make_user(s))
        assert await club.customer_summary(s, store, (await make_user(s)).id) == {"store_id": store.id, "enabled": False}


async def test_history_pages_newest_first():
    async with open_session() as s:
        store, customer, _, admin = await _world(s)
        for i in range(5):
            await club.adjust(s, store, customer.id, 10, reason=f"g{i}", actor_id=admin.id, actor_type="admin")
        await s.commit()
        page, more = await club.history(s, store.id, customer.id, limit=2)
        assert more is True and [t.memo for t in page] == ["g4", "g3"]
        rest, more2 = await club.history(s, store.id, customer.id, limit=10, before=page[-1].created_at)
        assert more2 is False and len(rest) <= 3


async def test_the_store_summary_counts_members_points_and_tiers():
    async with open_session() as s:
        store, customer, product, admin = await _world(s)
        reward = await _reward(s, store, admin, cost_points=10, value=2_000)
        await club.on_order_completed(s, (await _complete(s, customer, store, product, total=30_000)).id)
        await club.redeem(s, store, customer, reward.id, idempotency_key="k")
        await s.commit()
        stats = await club.store_summary(s, store.id)
        assert (stats["members"], stats["points_issued"], stats["points_redeemed"], stats["points_outstanding"]) == (1, 30, 10, 20)
        assert (stats["redemptions"], stats["value_paid"]) == (1, 2_000)
        assert stats["tiers"][0]["members"] == 1 and sum(t["members"] for t in stats["tiers"]) == 1
        assert stats["top_members"][0]["lifetime_earned"] == 30


async def test_earning_and_refunds_queue_customer_notifications_once():
    async with open_session() as s:
        store, customer, product, _ = await _world(s)
        order = await _complete(s, customer, store, product)
        await club.on_order_completed(s, order.id)
        await club.on_order_completed(s, order.id)
        await club.on_order_refunded(s, order.id)
        await s.commit()
        keys = (await s.scalars(select(OutboxEvent.dedup_key).where(OutboxEvent.dedup_key.like("notify:loyalty:%")))).all()
        assert len(keys) == len(set(keys)) == 2  # one for the earning, one for the reversal
