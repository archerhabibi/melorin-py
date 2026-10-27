"""Referral, commission and reward programmes are PER STORE (docs/17-Referral-Coupon-Store-Scope.md).

Each store (the main one, every reseller's shop and bot) has its own invite link, its own first-touch attribution, its own plan, its own
expense account and its own wallets. Nothing a customer does in one store changes what happens in another.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from _db import make_order, make_product, make_store, make_user, open_session
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core import deps, settings_store
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain.commission import Plan, PlanError, validate_plan
from melorin.kernel.models.catalog import StoreProduct
from melorin.kernel.models.referral import Commission, CommissionClawback, CommissionRule, ReferralRelationship
from melorin.kernel.models.stores import ResellerProfile, StoreMembership
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.wallet import Wallet
from melorin.modules.referral import router as referral_router
from melorin.modules.referral import service as referral

AUTH = "/api/v1/auth"
V1 = "/api/v1"


# ------------------------------------------------------------------ helpers
async def _join(s, store, *users):
    for u in users:
        s.add(StoreMembership(store_id=store.id, user_id=u.id, role="customer"))
    await s.flush()


async def _world(s):
    """main store + two reseller stores (A, B); a referrer who is a customer of all three."""
    main = await make_store(s, kind="main")
    owner_a, owner_b = await make_user(s), await make_user(s)
    store_a = await make_store(s, kind="reseller", owner=owner_a, slug="shop-a")
    store_b = await make_store(s, kind="reseller", owner=owner_b, slug="shop-b")
    referrer, friend = await make_user(s), await make_user(s)
    await _join(s, main, referrer)
    await _join(s, store_a, referrer)
    await _join(s, store_b, referrer)
    product = await make_product(s)
    await s.commit()
    return main, store_a, store_b, referrer, friend, product


async def _complete(s, user, store, product, *, total=1000, when=None):
    o = await make_order(s, user=user, store=store, product=product, total=total, status="completed")
    o.completed_at = when or utcnow()
    await s.commit()
    return o


async def _rule(s, store, kind, model, value, *, product=None, active=True, max_amount=None):
    s.add(
        CommissionRule(
            store_id=store.id,
            product_id=product.id if product else None,
            kind=kind,
            model=model,
            value=value,
            is_active=active,
            max_amount=max_amount,
        )
    )
    await s.commit()


# ------------------------------------------------------------------ plan definition rules (pure)
@pytest.mark.parametrize(
    ("plan", "code"),
    [
        (Plan("bogus", "fixed", 10), "REFERRAL_BAD_KIND"),
        (Plan("commission", "magic", 10), "REFERRAL_BAD_MODEL"),
        (Plan("commission", "fixed", -1), "REFERRAL_BAD_VALUE"),
        (Plan("commission", "percent", 10_001), "REFERRAL_BAD_VALUE"),
        (Plan("commission", "percent", 500, max_amount=0), "REFERRAL_BAD_CAP"),
    ],
)
def test_plan_rules_reject_with_their_code(plan, code):
    with pytest.raises(PlanError) as exc:
        validate_plan(plan)
    assert exc.value.code == code


def test_plan_rules_accept_sane_plans_and_check_in_order():
    validate_plan(Plan("signup_reward", "fixed", 500))
    validate_plan(Plan("commission", "percent", 10_000, max_amount=5000))  # 100 % is the ceiling, and allowed
    with pytest.raises(PlanError) as exc:  # kind is judged before the value
        validate_plan(Plan("nope", "percent", 99_999))
    assert exc.value.code == "REFERRAL_BAD_KIND"


# ------------------------------------------------------------------ attribution is per store
async def test_a_referrer_who_is_not_a_member_of_the_store_is_not_a_referral_there():
    async with open_session() as s:
        main, store_a, _, _, friend, _ = await _world(s)
        outsider = await make_user(s)  # customer of nothing
        assert await referral.attach(s, store_a.id, friend, outsider) is False
        assert (await s.scalars(select(ReferralRelationship))).all() == []


async def test_a_blocked_member_cannot_be_a_referrer():
    async with open_session() as s:
        main, store_a, _, referrer, friend, _ = await _world(s)
        m = await s.scalar(select(StoreMembership).where(StoreMembership.store_id == store_a.id, StoreMembership.user_id == referrer.id))
        m.status = "blocked"
        await s.commit()
        assert await referral.attach(s, store_a.id, friend, referrer) is False


async def test_the_store_owner_can_refer_in_his_own_store():
    async with open_session() as s:
        main, store_a, _, _, friend, _ = await _world(s)
        from melorin.kernel.models.identity import User

        owner = await s.get(User, store_a.owner_user_id)
        assert await referral.attach(s, store_a.id, friend, owner) is True


async def test_a_reseller_store_gets_its_own_first_touch_relationship():
    async with open_session() as s:
        main, store_a, store_b, referrer, friend, _ = await _world(s)
        other = await make_user(s)
        await _join(s, store_b, other)
        await s.commit()
        assert await referral.attach(s, store_a.id, friend, referrer) is True
        assert await referral.attach(s, store_a.id, friend, other) is False  # first touch wins INSIDE the store
        assert await referral.attach(s, store_b.id, friend, other) is True  # another store: independent relationship
        rows = (await s.scalars(select(ReferralRelationship).order_by(ReferralRelationship.created_at))).all()
        assert {(r.store_id, r.referrer_user_id) for r in rows} == {(store_a.id, referrer.id), (store_b.id, other.id)}


async def test_a_suspended_store_attaches_nothing():
    async with open_session() as s:
        main, store_a, _, referrer, friend, _ = await _world(s)
        store_a.status = "suspended"
        await s.commit()
        assert await referral.attach(s, store_a.id, friend, referrer) is False


async def test_an_existing_customer_of_the_store_cannot_be_claimed_by_a_late_link():
    async with open_session() as s:
        main, store_a, _, referrer, friend, product = await _world(s)
        await _join(s, store_a, friend)
        await _complete(s, friend, store_a, product)  # he already bought here
        assert await referral.attach(s, store_a.id, friend, referrer) is False
        # a purchase in ANOTHER store does not count as history here
        newcomer = await make_user(s)
        await _complete(s, newcomer, main, product)
        assert await referral.attach(s, store_a.id, newcomer, referrer) is True


async def test_mutual_referral_loops_and_self_referral_are_refused():
    async with open_session() as s:
        main, store_a, _, referrer, friend, _ = await _world(s)
        await _join(s, store_a, friend)
        assert await referral.attach(s, store_a.id, referrer, referrer) is False
        assert await referral.attach(s, store_a.id, friend, referrer) is True
        assert await referral.attach(s, store_a.id, referrer, friend) is False  # B cannot become A's referrer in the same store


# ------------------------------------------------------------------ rewards are paid inside the store, from its own plan
async def test_each_store_pays_only_its_own_plan_into_its_own_wallet():
    async with open_session() as s:
        main, store_a, store_b, referrer, friend, product = await _world(s)
        await _rule(s, main, "signup_reward", "fixed", 700)
        await _rule(s, store_a, "signup_reward", "fixed", 300)
        await _rule(s, store_b, "signup_reward", "fixed", 100)
        for st in (main, store_a):
            assert await referral.attach(s, st.id, friend, referrer) is True
        await s.commit()
        o_main = await _complete(s, friend, main, product)
        o_a = await _complete(s, friend, store_a, product)
        o_b = await _complete(s, friend, store_b, product)  # no relationship in B: pays nothing
        for o in (o_main, o_a, o_b):
            await referral.on_order_completed(s, o.id)
        await s.commit()
        rows = {c.store_id: c for c in (await s.scalars(select(Commission))).all()}
        assert set(rows) == {main.id, store_a.id}
        assert rows[main.id].amount == 700 and rows[store_a.id].amount == 300
        wallets = {w.store_id: w.balance for w in (await s.scalars(select(Wallet).where(Wallet.user_id == referrer.id))).all()}
        assert wallets == {main.id: 700, store_a.id: 300}  # each reward sits in the wallet of the store that paid it


async def test_a_reseller_store_never_inherits_the_main_stores_defaults():
    async with open_session() as s:
        main, store_a, _, referrer, friend, product = await _world(s)
        await settings_store.set_value(s, "referral.signup_reward", 900)  # the platform's legacy global default
        await s.commit()
        await referral.attach(s, store_a.id, friend, referrer)
        await s.commit()
        order = await _complete(s, friend, store_a, product)
        await referral.on_order_completed(s, order.id)
        await s.commit()
        assert (await s.scalars(select(Commission))).all() == []  # store A's owner configured nothing: it pays nothing


async def test_the_main_store_still_honours_the_legacy_global_defaults():
    async with open_session() as s:
        main, store_a, _, referrer, friend, product = await _world(s)
        await settings_store.set_value(s, "referral.signup_reward", 900)
        await s.commit()
        plan = await referral._plan(s, await make_order(s, user=friend, store=main, product=product), "signup_reward")
        assert plan is not None and (plan.model, plan.value) == ("fixed", 900)
        assert await referral._plan(s, await make_order(s, user=friend, store=store_a, product=product), "signup_reward") is None


async def test_first_purchase_reward_then_commission_inside_each_store_separately():
    async with open_session() as s:
        main, store_a, store_b, referrer, friend, product = await _world(s)
        await _rule(s, store_a, "signup_reward", "fixed", 300)
        await _rule(s, store_a, "commission", "percent", 1000)  # 10 %
        await _rule(s, store_b, "signup_reward", "fixed", 50)
        await referral.attach(s, store_a.id, friend, referrer)
        await referral.attach(s, store_b.id, friend, referrer)
        await s.commit()
        t0 = utcnow() - dt.timedelta(days=3)
        first_a = await _complete(s, friend, store_a, product, total=2000, when=t0)
        first_b = await _complete(s, friend, store_b, product, total=2000, when=t0 + dt.timedelta(hours=1))
        second_a = await _complete(s, friend, store_a, product, total=5000, when=t0 + dt.timedelta(days=1))
        for o in (first_a, first_b, second_a):
            await referral.on_order_completed(s, o.id)
        await s.commit()
        by = {(c.store_id, c.kind): c.amount for c in (await s.scalars(select(Commission))).all()}
        # a signup reward in EACH store (one per store per customer), the commission only in the store whose plan has one
        assert by == {(store_a.id, "signup_reward"): 300, (store_b.id, "signup_reward"): 50, (store_a.id, "commission"): 500}


async def test_product_specific_plan_wins_over_the_store_default():
    async with open_session() as s:
        main, store_a, _, referrer, friend, product = await _world(s)
        await _rule(s, store_a, "signup_reward", "fixed", 100)
        await _rule(s, store_a, "signup_reward", "fixed", 450, product=product)
        await referral.attach(s, store_a.id, friend, referrer)
        await s.commit()
        o = await _complete(s, friend, store_a, product)
        await referral.on_order_completed(s, o.id)
        await s.commit()
        assert (await s.scalar(select(Commission.amount))) == 450


async def test_refund_reverses_only_the_commission_of_that_store_and_tracks_the_clawback_there():
    async with open_session() as s:
        main, store_a, store_b, referrer, friend, product = await _world(s)
        await _rule(s, store_a, "signup_reward", "fixed", 300)
        await _rule(s, store_b, "signup_reward", "fixed", 300)
        await referral.attach(s, store_a.id, friend, referrer)
        await referral.attach(s, store_b.id, friend, referrer)
        await s.commit()
        oa = await _complete(s, friend, store_a, product)
        ob = await _complete(s, friend, store_b, product)
        for o in (oa, ob):
            await referral.on_order_completed(s, o.id)
        await s.commit()
        # the referrer spent his reward in store A already
        wa = await s.scalar(select(Wallet).where(Wallet.user_id == referrer.id, Wallet.store_id == store_a.id))
        wa.balance = 0
        await s.commit()
        await referral.on_order_refunded(s, oa.id)
        await s.commit()
        rows = {c.store_id: c for c in (await s.scalars(select(Commission))).all()}
        assert rows[store_a.id].status == "reversed" and rows[store_b.id].status == "credited"
        claw = (await s.scalars(select(CommissionClawback))).all()
        assert [(c.store_id, c.outstanding) for c in claw] == [(store_a.id, 300)]  # owed back to store A, nowhere else
        wb = await s.scalar(select(Wallet).where(Wallet.user_id == referrer.id, Wallet.store_id == store_b.id))
        assert wb.balance == 300  # store B's reward is untouched


# ------------------------------------------------------------------ plan management
async def test_upsert_rule_updates_the_one_default_plan_instead_of_duplicating_it():
    async with open_session() as s:
        main, store_a, _, _, _, _ = await _world(s)
        actor = await make_user(s)
        for value in (100, 250):
            await referral.upsert_rule(
                s,
                store_a,
                product_id=None,
                kind="signup_reward",
                model="fixed",
                value=value,
                max_amount=None,
                is_active=True,
                actor_id=actor.id,
                actor_type="reseller",
            )
            await s.commit()
        rows = (await s.scalars(select(CommissionRule).where(CommissionRule.store_id == store_a.id))).all()
        assert len(rows) == 1 and rows[0].value == 250
        audits = (await s.scalars(select(AuditEvent).where(AuditEvent.action == "referral.rule.saved"))).all()
        assert len(audits) == 2 and audits[-1].data["before"]["value"] == 100 and audits[-1].data["after"]["value"] == 250


async def test_upsert_rule_refuses_a_product_the_reseller_store_does_not_sell_and_bad_numbers():
    async with open_session() as s:
        main, store_a, _, _, _, product = await _world(s)
        actor = await make_user(s)
        with pytest.raises(AppError) as exc:
            await referral.upsert_rule(
                s,
                store_a,
                product_id=product.id,
                kind="commission",
                model="percent",
                value=500,
                max_amount=None,
                is_active=True,
                actor_id=actor.id,
                actor_type="reseller",
            )
        assert exc.value.code == "REFERRAL_PRODUCT_NOT_IN_STORE"
        s.add(StoreProduct(store_id=store_a.id, product_id=product.id, is_enabled=True))
        await s.commit()
        row = await referral.upsert_rule(
            s,
            store_a,
            product_id=product.id,
            kind="commission",
            model="percent",
            value=500,
            max_amount=None,
            is_active=True,
            actor_id=actor.id,
            actor_type="reseller",
        )
        assert row.product_id == product.id
        with pytest.raises(AppError) as exc:
            await referral.upsert_rule(
                s,
                store_a,
                product_id=None,
                kind="commission",
                model="percent",
                value=20_000,
                max_amount=None,
                is_active=True,
                actor_id=actor.id,
                actor_type="reseller",
            )
        assert exc.value.code == "REFERRAL_BAD_VALUE"


async def test_programme_and_summary_describe_one_store_only():
    async with open_session() as s:
        main, store_a, store_b, referrer, friend, product = await _world(s)
        await _rule(s, store_a, "signup_reward", "fixed", 300)
        await _rule(s, store_a, "commission", "percent", 1000)
        await _rule(s, store_b, "signup_reward", "fixed", 77)
        for st in (store_a, store_b):
            await referral.attach(s, st.id, friend, referrer)
        await s.commit()
        for st in (store_a, store_b):
            o = await _complete(s, friend, st, product)
            await referral.on_order_completed(s, o.id)
        await s.commit()
        program = await referral.program_for(s, store_a)
        assert program["enabled"] is True and program["signup_reward"]["value"] == 300 and program["commission"]["value"] == 1000
        assert "commission" not in await referral.program_for(s, store_b)
        summary = await referral.store_summary(s, store_a.id)
        assert summary["invited"] == 1 and summary["referrers"] == 1 and summary["paid_out"] == 300
        assert summary["top_referrers"][0]["user_id"] == referrer.id and summary["top_referrers"][0]["paid"] == 300
        assert (await referral.store_summary(s, store_b.id))["paid_out"] == 77  # B's own number, not A's
        empty = await referral.store_summary(s, main.id)
        assert empty["invited"] == 0 and empty["paid_out"] == 0 and empty["top_referrers"] == []


# ------------------------------------------------------------------ the sign-up hook (identity)
async def test_signup_hook_attaches_new_members_only_and_never_an_existing_member():
    from melorin.modules.identity.routes._common import _after_signup

    async with open_session() as s:
        main, store_a, _, referrer, friend, _ = await _world(s)
        veteran = await make_user(s)
        await _join(s, store_a, veteran)
        await s.commit()
        await _after_signup(s, friend, True, store_a.id, referrer.referral_code)  # brand new account
        await _after_signup(s, veteran, False, store_a.id, referrer.referral_code)  # already a member here: ignored
        joiner = await make_user(s)  # existing platform account joining THIS store for the first time
        await _after_signup(s, joiner, False, store_a.id, referrer.referral_code)
        await s.commit()
        got = {r.referred_user_id for r in (await s.scalars(select(ReferralRelationship))).all()}
        assert got == {friend.id, joiner.id}


async def test_signup_hook_ignores_a_code_whose_owner_is_not_in_the_store():
    from melorin.modules.identity.routes._common import _after_signup

    async with open_session() as s:
        main, store_a, _, _, friend, _ = await _world(s)
        stranger = await make_user(s)  # a customer of no store at all
        await _after_signup(s, friend, True, store_a.id, stranger.referral_code)
        await _after_signup(s, friend, True, store_a.id, "nosuchcode")
        await s.commit()
        assert (await s.scalars(select(ReferralRelationship))).all() == []


# ------------------------------------------------------------------ customer plane: his link, this store's programme
async def test_customer_sees_the_programme_links_and_standing_of_the_store_he_is_in():
    async with open_session() as s:
        main, store_a, store_b, referrer, friend, product = await _world(s)
        store_a.domain, store_a.bot_username = "shop-a.example.com", "shop_a_bot"
        await _rule(s, store_a, "signup_reward", "fixed", 300)
        await referral.attach(s, store_a.id, friend, referrer)
        await referral.attach(s, store_b.id, friend, referrer)
        await s.commit()
        o = await _complete(s, friend, store_a, product)
        await referral.on_order_completed(s, o.id)
        await s.commit()
        ctx = await deps.resolve_store_context(s, store_a.id, referrer)
        out = await referral_router.store_referral(ctx, s)
        assert out["store_id"] == store_a.id and out["invited"] == 1 and out["earned"] == 300
        assert out["links"] == {
            "web": f"https://shop-a.example.com/?ref={referrer.referral_code}",
            "telegram": f"https://t.me/shop_a_bot?start=ref_{referrer.referral_code}",
        }
        assert out["program"]["enabled"] and all(c["store_id"] == store_a.id for c in out["commissions"])
        other = await referral_router.store_referral(await deps.resolve_store_context(s, store_b.id, referrer), s)
        assert other["invited"] == 1 and other["earned"] == 0 and other["links"] == {"web": None, "telegram": None}
        assert other["program"]["enabled"] is False


# ------------------------------------------------------------------ /me/referrals: what the bots show, strictly the session's store
def _session_of(user, store, *, admin=False):
    """The slice of ``AuthSession`` the handler reads: who, and which store (and role) the token is bound to."""
    return SimpleNamespace(user=user, claims=SimpleNamespace(is_admin=admin, store_id=store.id))


async def _two_store_standing(s):
    """The referrer invited a friend in BOTH reseller stores and earned a different reward in each."""
    main, store_a, store_b, referrer, friend, product = await _world(s)
    store_a.domain, store_a.bot_username, store_a.currency = "shop-a.example.com", "shop_a_bot", "IRT"
    store_b.domain, store_b.bot_username, store_b.currency = "shop-b.example.com", "shop_b_bot", "USDT"
    await _rule(s, store_a, "signup_reward", "fixed", 300)
    await _rule(s, store_b, "signup_reward", "fixed", 7)
    for st in (store_a, store_b):
        await referral.attach(s, st.id, friend, referrer)
    await s.commit()
    for st in (store_a, store_b):
        o = await _complete(s, friend, st, product)
        await referral.on_order_completed(s, o.id)
        await s.commit()
    return store_a, store_b, referrer


async def test_the_bots_referral_view_is_the_programme_link_and_earnings_of_the_session_store_only():
    async with open_session() as s:
        store_a, store_b, referrer = await _two_store_standing(s)
        a = await referral_router.my_referrals(_session_of(referrer, store_a), s)
        assert a["referred_count"] == 1 and a["links"]["telegram"] == f"https://t.me/shop_a_bot?start=ref_{referrer.referral_code}"
        assert {c["store_id"] for c in a["commissions"]} == {store_a.id} and [c["amount"] for c in a["commissions"]] == [300]
        assert a["program"]["enabled"] and a["program"]["signup_reward"]["value"] == 300
        b = await referral_router.my_referrals(_session_of(referrer, store_b), s)
        assert b["links"]["telegram"] == f"https://t.me/shop_b_bot?start=ref_{referrer.referral_code}"
        assert {c["store_id"] for c in b["commissions"]} == {store_b.id} and [c["amount"] for c in b["commissions"]] == [7]
        assert b["program"]["signup_reward"]["value"] == 7


async def test_an_admin_flagged_session_bound_to_a_store_still_sees_only_that_store():
    """A platform admin who opens a reseller's bot must not get every store's invites and commissions mixed into its screen."""
    async with open_session() as s:
        store_a, store_b, referrer = await _two_store_standing(s)
        out = await referral_router.my_referrals(_session_of(referrer, store_a, admin=True), s)
        assert out["referred_count"] == 1
        assert {c["store_id"] for c in out["commissions"]} == {store_a.id}
        assert {c["currency"] for c in out["commissions"]} == {"IRT"}


# ------------------------------------------------------------------ HTTP: a reseller manages only his own store's programme
async def _hub_headers(c, email):
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _reseller_world(c, maker):
    owner_a = await add_user(maker, email="a@example.com")
    owner_b = await add_user(maker, email="b@example.com")
    await add_user(maker, email="stranger@example.com")
    async with maker() as s:
        store_a = await make_store(s, kind="reseller", owner=owner_a, slug="shop-a")
        store_b = await make_store(s, kind="reseller", owner=owner_b, slug="shop-b")
        for st, owner in ((store_a, owner_a), (store_b, owner_b)):
            s.add(ResellerProfile(store_id=st.id, user_id=owner.id, debt_limit=5000, api_enabled=False, sales_enabled=True))
        await s.commit()
    return store_a, store_b, {w: await _hub_headers(c, f"{w}@example.com") for w in ("a", "b", "stranger")}


def _code(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


async def test_owner_manages_the_programme_of_his_own_store_and_no_other():
    async with api_client() as (c, maker, main):
        store_a, store_b, h = await _reseller_world(c, maker)
        body = {"kind": "signup_reward", "model": "fixed", "value": 400}
        ok = await c.put(f"{V1}/stores/{store_a.id}/referral-rules", headers=h["a"], json=body)
        assert ok.status_code == 200 and ok.json()["store_id"] == str(store_a.id) and ok.json()["value"] == 400
        again = await c.put(f"{V1}/stores/{store_a.id}/referral-rules", headers=h["a"], json={**body, "value": 450})
        assert again.json()["id"] == ok.json()["id"] and again.json()["value"] == 450  # one default plan, updated in place
        listed = await c.get(f"{V1}/stores/{store_a.id}/referral-rules", headers=h["a"])
        assert [r["value"] for r in listed.json()] == [450]
        # owner B and a stranger can neither read nor write store A's programme, nor reach its numbers
        for who in ("b", "stranger"):
            for r in (
                await c.put(f"{V1}/stores/{store_a.id}/referral-rules", headers=h[who], json=body),
                await c.get(f"{V1}/stores/{store_a.id}/referral-rules", headers=h[who]),
                await c.get(f"{V1}/stores/{store_a.id}/referrals/summary", headers=h[who]),
            ):
                assert r.status_code == 403, (who, r.text)
        async with maker() as s:
            assert (await s.scalar(select(func.count()).select_from(CommissionRule).where(CommissionRule.store_id == store_b.id))) == 0
            assert await s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "referral.rule.saved")) == 2


async def test_owner_cannot_name_another_store_or_an_unsafe_plan():
    async with api_client() as (c, maker, main):
        store_a, store_b, h = await _reseller_world(c, maker)
        # the store of a plan is the URL's, never a body field: a spoofed store_id changes nothing
        r = await c.put(
            f"{V1}/stores/{store_a.id}/referral-rules",
            headers=h["a"],
            json={"kind": "commission", "model": "percent", "value": 500, "store_id": str(store_b.id)},
        )
        assert r.status_code == 200 and r.json()["store_id"] == str(store_a.id)
        too_much = await c.put(
            f"{V1}/stores/{store_a.id}/referral-rules", headers=h["a"], json={"kind": "commission", "model": "percent", "value": 10_001}
        )
        assert too_much.status_code == 400 and _code(too_much) == "REFERRAL_BAD_VALUE"
        foreign_product = await make_foreign_product(maker)
        bad = await c.put(
            f"{V1}/stores/{store_a.id}/referral-rules",
            headers=h["a"],
            json={"kind": "commission", "model": "percent", "value": 100, "product_id": str(foreign_product)},
        )
        assert bad.status_code == 400 and _code(bad) == "REFERRAL_PRODUCT_NOT_IN_STORE"
        async with maker() as s:
            assert (await s.scalar(select(func.count()).select_from(CommissionRule).where(CommissionRule.store_id == store_b.id))) == 0


async def make_foreign_product(maker):
    async with maker() as s:
        product = await make_product(s)
        await s.commit()
        return product.id


async def test_owner_summary_is_the_stores_own_and_the_main_store_is_not_an_owner_plane_target():
    async with api_client() as (c, maker, main):
        store_a, store_b, h = await _reseller_world(c, maker)
        r = await c.get(f"{V1}/stores/{store_a.id}/referrals/summary", headers=h["a"])
        assert r.status_code == 200 and r.json()["store_id"] == str(store_a.id) and r.json()["invited"] == 0
        # the main store's programme is Admin's: the owner plane refuses it even for a main-store hub session
        assert (await c.get(f"{V1}/stores/{main.id}/referral-rules", headers=h["a"])).status_code == 403


async def test_admin_can_manage_and_inspect_any_store_and_unknown_stores_are_404():
    async with api_client() as (c, maker, main):
        store_a, store_b, _ = await _reseller_world(c, maker)
        await add_user(maker, email="root@example.com", admin=True, totp=True)
        r = await c.post(f"{AUTH}/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
        assert r.status_code == 200, r.text
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        body = {"store_id": str(store_b.id), "kind": "commission", "model": "percent", "value": 250}
        ok = await c.put(f"{V1}/admin/referral-rules", headers=h, json=body)
        assert ok.status_code == 200 and ok.json()["store_id"] == str(store_b.id)
        only_b = await c.get(f"{V1}/admin/referral-rules", headers=h, params={"store_id": str(store_b.id)})
        assert [r["store_id"] for r in only_b.json()] == [str(store_b.id)]
        assert (await c.get(f"{V1}/admin/stores/{store_b.id}/referrals/summary", headers=h)).status_code == 200
        missing = "00000000-0000-0000-0000-000000000001"
        assert (await c.put(f"{V1}/admin/referral-rules", headers=h, json={**body, "store_id": missing})).status_code == 404
        assert (await c.get(f"{V1}/admin/stores/{missing}/referrals/summary", headers=h)).status_code == 404
        assert (await c.put(f"{V1}/admin/referral-rules", headers=h, json={**body, "value": 10_001})).status_code == 400


# ------------------------------------------------------------------ refund of the first order must not break the next one
async def test_after_the_first_order_is_refunded_the_next_order_earns_a_plain_commission_and_never_a_second_signup_reward():
    """The signup reward is one per customer per store (unique key). When that first order is refunded, the customer is still
    not 'new' for the programme: the next completed order pays the commission plan, it must not try to pay the reward again."""
    async with open_session() as s:
        main, store_a, _, referrer, friend, product = await _world(s)
        await _rule(s, store_a, "signup_reward", "fixed", 300)
        await _rule(s, store_a, "commission", "percent", 1000)
        await referral.attach(s, store_a.id, friend, referrer)
        await s.commit()
        t0 = utcnow()
        first = await _complete(s, friend, store_a, product, when=t0 - dt.timedelta(days=2))
        await referral.on_order_completed(s, first.id)
        await s.commit()
        await referral.on_order_refunded(s, first.id)
        first.status = "refunded"
        await s.commit()
        second = await _complete(s, friend, store_a, product, total=2000, when=t0)
        await referral.on_order_completed(s, second.id)  # must not raise
        await s.commit()
        rows = {(c.order_id, c.kind): c for c in (await s.scalars(select(Commission))).all()}
        assert rows[(first.id, "signup_reward")].status == "reversed"
        assert rows[(second.id, "commission")].amount == 200  # 10 % of 2000
        assert (second.id, "signup_reward") not in rows
