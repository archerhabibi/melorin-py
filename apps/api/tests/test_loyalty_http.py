"""Loyalty club over HTTP and through the worker (docs/22): who may manage which club, what a customer sees and spends."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from _db import make_order, make_product, make_store
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.db import utcnow
from melorin.kernel.models.loyalty import LoyaltyAccount, LoyaltyTransaction
from melorin.kernel.models.stores import ResellerProfile
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.wallet import Wallet
from melorin.modules.loyalty import service as club
from melorin.worker import runner

AUTH = "/api/v1/auth"
V1 = "/api/v1"
PROGRAM = {"enabled": True, "earn_unit": 1000, "points_per_unit": 1, "first_order_bonus": 0, "referral_bonus": 0}
REWARD = {"name": "credit", "kind": "wallet_credit", "value": 5000, "cost_points": 100}


def _code(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


async def _login(c, email, **extra):
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD, **extra})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _admin(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    return await _login(c, "root@example.com", totp_code=totp_now())


async def _resellers(c, maker):
    owner_a, owner_b = await add_user(maker, email="a@example.com"), await add_user(maker, email="b@example.com")
    await add_user(maker, email="stranger@example.com")
    async with maker() as s:
        store_a = await make_store(s, kind="reseller", owner=owner_a, slug="shop-a")
        store_b = await make_store(s, kind="reseller", owner=owner_b, slug="shop-b")
        for st, owner in ((store_a, owner_a), (store_b, owner_b)):
            s.add(ResellerProfile(store_id=st.id, user_id=owner.id, debt_limit=5000, api_enabled=False, sales_enabled=True))
        await s.commit()
    return store_a, store_b, {w: await _login(c, f"{w}@example.com") for w in ("a", "b", "stranger")}


async def _complete(maker, user_id, store, *, total=10_000):
    async with maker() as s:
        product = await make_product(s)
        from melorin.kernel.models.identity import User

        user = await s.get(User, user_id)
        o = await make_order(s, user=user, store=store, product=product, total=total, status="completed")
        o.completed_at = utcnow() + dt.timedelta(microseconds=1)
        await s.commit()
        return o.id


# ------------------------------------------------------------------ who may manage which club
async def test_owner_manages_the_club_of_his_own_store_and_no_other():
    async with api_client() as (c, maker, main):
        store_a, store_b, h = await _resellers(c, maker)
        base = f"{V1}/stores/{store_a.id}/loyalty/manage"
        ok = await c.put(f"{base}/program", headers=h["a"], json=PROGRAM)
        assert ok.status_code == 200 and ok.json()["enabled"] is True
        got = await c.get(f"{base}/program", headers=h["a"])
        assert got.json()["program"]["earn_unit"] == 1000 and len(got.json()["tiers"]) == 4  # default ladder seeded
        created = await c.post(f"{base}/rewards", headers=h["a"], json=REWARD)
        assert created.status_code == 201 and created.json()["remaining"] is None
        listed = await c.get(f"{base}/rewards", headers=h["a"])
        assert [r["name"] for r in listed.json()] == ["credit"]
        for who in ("b", "stranger"):
            for r in (
                await c.put(f"{base}/program", headers=h[who], json=PROGRAM),
                await c.get(f"{base}/program", headers=h[who]),
                await c.post(f"{base}/rewards", headers=h[who], json=REWARD),
                await c.get(f"{base}/summary", headers=h[who]),
                await c.put(f"{base}/tiers", headers=h[who], json={"tiers": [{"name": "x", "min_points": 0}]}),
            ):
                assert r.status_code == 403, (who, r.text)
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "loyalty.program.saved")) == 1


async def test_a_reseller_cannot_manage_the_main_store_but_admin_can_manage_any_store():
    async with api_client() as (c, maker, main):
        store_a, _, h = await _resellers(c, maker)
        assert (await c.put(f"{V1}/stores/{main.id}/loyalty/manage/program", headers=h["a"], json=PROGRAM)).status_code == 403
        admin = await _admin(c, maker)
        for store in (main, store_a):
            ok = await c.put(f"{V1}/stores/{store.id}/loyalty/manage/program", headers=admin, json=PROGRAM)
            assert ok.status_code == 200, ok.text
        missing = "00000000-0000-0000-0000-000000000001"
        assert (await c.get(f"{V1}/stores/{missing}/loyalty/manage/program", headers=admin)).status_code == 404


async def test_bad_definitions_are_refused_with_their_code():
    async with api_client() as (c, maker, main):
        store_a, _, h = await _resellers(c, maker)
        base = f"{V1}/stores/{store_a.id}/loyalty/manage"
        bad_tiers = await c.put(f"{base}/tiers", headers=h["a"], json={"tiers": [{"name": "only", "min_points": 10}]})
        assert bad_tiers.status_code == 400 and _code(bad_tiers) == "LOYALTY_TIERS_START"
        bad_reward = await c.post(f"{base}/rewards", headers=h["a"], json={**REWARD, "kind": "gift_card"})
        assert bad_reward.status_code == 400 and _code(bad_reward) == "LOYALTY_BAD_REWARD_KIND"
        out_of_range = await c.put(f"{base}/program", headers=h["a"], json={**PROGRAM, "earn_unit": 0})
        assert out_of_range.status_code == 422
        ok = await c.put(
            f"{base}/tiers",
            headers=h["a"],
            json={"tiers": [{"name": "base", "min_points": 0}, {"name": "vip", "min_points": 50, "multiplier_bp": 20000}]},
        )
        assert ok.status_code == 200 and [t["name"] for t in ok.json()] == ["base", "vip"]


async def test_a_reward_id_of_another_store_is_not_found_for_the_owner():
    async with api_client() as (c, maker, main):
        store_a, store_b, h = await _resellers(c, maker)
        mine = (await c.post(f"{V1}/stores/{store_a.id}/loyalty/manage/rewards", headers=h["a"], json=REWARD)).json()["id"]
        hijack = await c.put(f"{V1}/stores/{store_b.id}/loyalty/manage/rewards/{mine}", headers=h["b"], json=REWARD)
        assert hijack.status_code == 404


# ------------------------------------------------------------------ what a customer sees and spends (main store hub session)
async def test_customer_sees_points_and_redeems_a_reward_once_per_idempotency_key():
    async with api_client() as (c, maker, main):
        admin = await _admin(c, maker)
        customer = await add_user(maker, email="cust@example.com")
        ch = await _login(c, "cust@example.com")
        mine = f"{V1}/stores/{main.id}/loyalty"
        assert (await c.get(mine, headers=ch)).json() == {"store_id": str(main.id), "enabled": False}
        await c.put(f"{mine}/manage/program", headers=admin, json=PROGRAM)
        reward = (await c.post(f"{mine}/manage/rewards", headers=admin, json=REWARD)).json()
        order_id = await _complete(maker, customer.id, main, total=150_000)
        async with maker() as s:
            await club.on_order_completed(s, order_id)
            await s.commit()
        view = (await c.get(mine, headers=ch)).json()
        assert view["balance"] == 150 and view["tier"]["name"] and view["rewards"][0]["available"] is True
        key = {"Idempotency-Key": "redeem-key-0001"}
        first = await c.post(f"{mine}/rewards/{reward['id']}/redeem", headers={**ch, **key})
        again = await c.post(f"{mine}/rewards/{reward['id']}/redeem", headers={**ch, **key})
        assert first.status_code == again.status_code == 200
        assert (first.json()["replayed"], again.json()["replayed"]) == (False, True) and again.json()["balance"] == 50
        assert first.json()["id"] == again.json()["id"]
        async with maker() as s:
            wallet = await s.scalar(select(Wallet).where(Wallet.user_id == customer.id, Wallet.store_id == main.id))
            assert wallet.balance == 5_000  # credited once
        too_dear = await c.post(f"{mine}/rewards/{reward['id']}/redeem", headers={**ch, "Idempotency-Key": "redeem-key-0002"})
        assert too_dear.status_code == 400 and _code(too_dear) == "LOYALTY_NOT_ENOUGH_POINTS"
        assert (await c.post(f"{mine}/rewards/{reward['id']}/redeem", headers={**ch, "Idempotency-Key": "short"})).status_code == 422
        history = (await c.get(f"{mine}/history", headers=ch, params={"limit": 1})).json()
        assert history["has_more"] is True and history["items"][0]["kind"] == "redeem"
        spent = (await c.get(f"{mine}/redemptions", headers=ch)).json()
        assert [r["points_spent"] for r in spent] == [100]


async def test_a_customer_cannot_manage_or_read_another_stores_club():
    async with api_client() as (c, maker, main):
        store_a, _, h = await _resellers(c, maker)
        await add_user(maker, email="cust@example.com")
        ch = await _login(c, "cust@example.com")
        assert (await c.put(f"{V1}/stores/{main.id}/loyalty/manage/program", headers=ch, json=PROGRAM)).status_code == 403
        assert (await c.get(f"{V1}/stores/{store_a.id}/loyalty", headers=ch)).status_code in (401, 403)  # session belongs to the main store


async def test_admin_adjusts_points_with_a_reason_and_the_summary_reflects_it():
    async with api_client() as (c, maker, main):
        admin = await _admin(c, maker)
        customer = await add_user(maker, email="cust@example.com")
        async with maker() as s:
            from melorin.kernel.models.stores import StoreMembership

            s.add(StoreMembership(store_id=main.id, user_id=customer.id, role="customer"))
            await s.commit()
        base = f"{V1}/stores/{main.id}/loyalty/manage"
        await c.put(f"{base}/program", headers=admin, json=PROGRAM)
        grant = await c.post(f"{base}/adjust", headers=admin, json={"user_id": str(customer.id), "delta": 80, "reason": "welcome gift"})
        assert grant.status_code == 200 and grant.json()["balance_after"] == 80
        no_reason = await c.post(f"{base}/adjust", headers=admin, json={"user_id": str(customer.id), "delta": 5, "reason": "   "})
        assert no_reason.status_code == 400 and _code(no_reason) == "LOYALTY_REASON_REQUIRED"
        overdraw = await c.post(f"{base}/adjust", headers=admin, json={"user_id": str(customer.id), "delta": -999, "reason": "x"})
        assert overdraw.status_code == 400 and _code(overdraw) == "LOYALTY_NOT_ENOUGH_POINTS"
        stats = (await c.get(f"{base}/summary", headers=admin)).json()
        assert stats["members"] == 1 and stats["points_outstanding"] == 80 and stats["top_members"][0]["lifetime_earned"] == 80


# ------------------------------------------------------------------ the worker wiring
async def test_the_outbox_handlers_pay_and_take_back_club_points(monkeypatch):
    async def _no_webhook(*a, **k):
        return None

    monkeypatch.setattr(runner, "_webhook", _no_webhook)
    async with api_client() as (c, maker, main):
        customer = await add_user(maker, email="cust@example.com")
        async with maker() as s:
            await club.upsert_program(
                s,
                main,
                enabled=True,
                earn_unit=1000,
                points_per_unit=1,
                max_points_per_order=None,
                first_order_bonus=0,
                referral_bonus=0,
                actor_id=customer.id,
                actor_type="admin",
            )
            await s.commit()
        order_id = await _complete(maker, customer.id, main, total=25_000)
        async with maker() as s:
            await runner._on_order_completed(s, {"order_id": str(order_id)})
            await s.commit()
        async with maker() as s:
            acc = await s.scalar(select(LoyaltyAccount).where(LoyaltyAccount.user_id == customer.id))
            assert acc.balance == 25
        async with maker() as s:
            await runner._on_order_refunded(s, {"order_id": str(order_id)})
            await s.commit()
        async with maker() as s:
            acc = await s.scalar(select(LoyaltyAccount).where(LoyaltyAccount.user_id == customer.id))
            assert (acc.balance, acc.lifetime_earned) == (0, 0)
            kinds = (await s.scalars(select(LoyaltyTransaction.kind).order_by(LoyaltyTransaction.created_at))).all()
            assert kinds == ["order_earn", "reversal"]
