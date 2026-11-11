"""The numeric Telegram ID is shown next to the wallet: customer wallet, reseller customer list (panel and API)."""

from __future__ import annotations

from _db import make_store
from _http import PASSWORD, add_user, api_client
from melorin.core.db import utcnow
from melorin.kernel.models.identity import Identity, User
from melorin.kernel.models.stores import ResellerProfile, StoreMembership

AUTH = "/api/v1/auth"
V1 = "/api/v1"


async def _link_telegram(maker, user_id, tg_id: str) -> None:
    async with maker() as s:
        s.add(Identity(user_id=user_id, provider="telegram", subject=tg_id, verified_at=utcnow(), data={}))
        await s.commit()


async def _login(c, email):
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["store_id"]


async def test_wallet_shows_the_telegram_id_of_its_owner_or_none():
    async with api_client() as (c, maker, main):
        user = await add_user(maker, email="u@example.com")
        h, sid = await _login(c, "u@example.com")
        assert (await c.get(f"{V1}/stores/{sid}/wallet", headers=h)).json()["telegram_id"] is None
        await _link_telegram(maker, user.id, "123456789")
        assert (await c.get(f"{V1}/stores/{sid}/wallet", headers=h)).json()["telegram_id"] == "123456789"


async def test_a_wallet_never_shows_another_users_telegram_id():
    async with api_client() as (c, maker, main):
        await add_user(maker, email="u@example.com")
        other = await add_user(maker, email="o@example.com")
        await _link_telegram(maker, other.id, "987654321")
        h, sid = await _login(c, "u@example.com")
        assert (await c.get(f"{V1}/stores/{sid}/wallet", headers=h)).json()["telegram_id"] is None


async def test_reseller_customer_list_and_api_carry_each_customers_telegram_id():
    async with api_client() as (c, maker, main):
        owner = await add_user(maker, email="a@example.com")
        async with maker() as s:
            store = await make_store(s, kind="reseller", owner=owner, slug="shop-a")
            s.add(ResellerProfile(store_id=store.id, user_id=owner.id, debt_limit=5000, api_enabled=True, sales_enabled=True))
            with_tg = User(email="tg@example.com", display_name="tg", is_active=True)
            without = User(email="plain@example.com", display_name="plain", is_active=True)
            s.add_all([with_tg, without])
            await s.flush()
            for u in (with_tg, without):
                s.add(StoreMembership(store_id=store.id, user_id=u.id, role="customer", status="active"))
            await s.commit()
        await _link_telegram(maker, with_tg.id, "555000111")
        h, _ = await _login(c, "a@example.com")

        rows = (await c.get(f"{V1}/stores/{store.id}/reseller/customers", headers=h)).json()
        assert {r["email"]: r["telegram_id"] for r in rows} == {"tg@example.com": "555000111", "plain@example.com": None}

        key = (
            await c.post(f"{V1}/stores/{store.id}/reseller/api-credentials", headers=h, json={"name": "erp", "scopes": ["customers:read"]})
        ).json()
        api_rows = (await c.get(f"{V1}/reseller-api/v1/stores/{store.id}/customers", headers={"X-API-Key": key["api_key"]})).json()
        assert {r["email"]: r["telegram_id"] for r in api_rows} == {"tg@example.com": "555000111", "plain@example.com": None}
