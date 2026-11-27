"""An admin account is also an ordinary customer in the bots: same account, same wallet, customer session, no admin rights."""

from __future__ import annotations

import types

import pytest
from sqlalchemy import select

from _http import add_user, api_client
from melorin.core import admin_telegram
from melorin.core import channel as ch
from melorin.kernel.models.identity import Identity, User

pytestmark = pytest.mark.asyncio

BOT_LOGIN = "/api/v1/auth/telegram/bot"
MAIN_SECRET = {"X-Bot-Secret": "m" * 40}
SECRETS = types.SimpleNamespace(
    is_dev=False,
    trusted_proxy_ips=["172.28.0.0/16"],
    store_web_url="https://main.example.com",
    public_api_url="https://main.example.com",
    bot_service_secret="s" * 40,
    main_bot_secret="m" * 40,
    reseller_bot_secret="r" * 40,
)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(ch, "get_settings", lambda: SECRETS)


def _login(main, telegram_id):
    return {"telegram_id": telegram_id, "first_name": "Admin", "store_id": str(main.id)}


async def _admin_with_telegram(maker, tg="424242424", email="root@example.com"):
    admin = await add_user(maker, email=email, admin=True, totp=True)
    async with maker() as s:
        await admin_telegram.link(s, await s.get(User, admin.id), tg)
        await s.commit()
    return admin


async def test_the_admins_telegram_opens_a_customer_session_of_the_admins_own_account():
    async with api_client() as (c, maker, main):
        admin = await _admin_with_telegram(maker)
        r = await c.post(BOT_LOGIN, json=_login(main, 424242424), headers=MAIN_SECRET)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_admin"] is False and body["channel"] == "bot" and body["admin_account"] is True
        assert body["user_id"] == str(admin.id)  # one account: the admin's own wallet and orders
        h = {"Authorization": f"Bearer {body['access_token']}"}
        # the customer plane works ...
        assert (await c.get(f"/api/v1/stores/{main.id}/wallet", headers=h)).status_code == 200
        # ... and the admin plane stays shut for this session
        assert (await c.get("/api/v1/admin/telegram/channel-join", headers=h)).status_code == 403


async def test_every_admin_can_use_the_bot_and_a_plain_customer_is_not_flagged():
    async with api_client() as (c, maker, main):
        a1 = await _admin_with_telegram(maker, "111111111", "a1@example.com")
        a2 = await _admin_with_telegram(maker, "222222222", "a2@example.com")
        for tg, admin in ((111111111, a1), (222222222, a2)):
            r = await c.post(BOT_LOGIN, json=_login(main, tg), headers=MAIN_SECRET)
            assert r.status_code == 200, r.text
            assert r.json()["user_id"] == str(admin.id) and r.json()["admin_account"] is True
        r = await c.post(BOT_LOGIN, json=_login(main, 555000111), headers=MAIN_SECRET)
        assert r.status_code == 200 and r.json()["admin_account"] is False and r.json()["is_admin"] is False
        async with maker() as s:
            assert (await s.scalar(select(Identity).where(Identity.subject == "555000111"))) is not None
            assert len((await s.scalars(select(User).where(User.is_super_admin.is_(True)))).all()) == 2


async def test_an_admin_session_still_needs_the_panel_login():
    """The Telegram ID alone never yields an admin session: only password + TOTP does."""
    async with api_client() as (c, maker, main):
        await _admin_with_telegram(maker)
        r = await c.post(BOT_LOGIN, json=_login(main, 424242424), headers=MAIN_SECRET)
        claims = ch.SessionClaims.from_payload(
            __import__("melorin.core.security", fromlist=["x"]).decode_access_token(r.json()["access_token"])
        )
        assert claims.channel == "bot" and not claims.is_admin


# ---- the golden purchase path, driven by the admin's own Telegram (bot session) -------------------------------------
import uuid  # noqa: E402

from _db import make_product  # noqa: E402
from melorin.kernel.models.bundles import Bundle, BundleMember, BundleProduct  # noqa: E402
from melorin.kernel.models.catalog import StoreProduct  # noqa: E402
from melorin.kernel.models.payments import Payment  # noqa: E402
from melorin.kernel.models.stores import StorePaymentConfiguration  # noqa: E402
from melorin.kernel.models.vpn import Panel, Server  # noqa: E402
from melorin.modules.orders import provisioning as vpn  # noqa: E402
from test_golden_purchase_flow import world  # noqa: E402,F401  (fixture: fake gateway + fake panel)


async def test_the_admin_tops_up_buys_and_gets_an_account_through_the_bot(world):
    price = 2_000
    async with api_client() as (c, maker, main):
        async with maker() as s:
            product = await make_product(s, price=price)
            group = Bundle(name="G", selection_mode="automatic", is_enabled=True)
            panel = Panel(name="P1", kind="mock", base_url="http://x", is_enabled=True, health_status="healthy")
            s.add_all([group, panel])
            await s.flush()
            s.add_all(
                [BundleMember(bundle_id=group.id, panel_id=panel.id, sort=0), BundleProduct(bundle_id=group.id, product_id=product.id)]
            )
            s.add(Server(name="S1", panel_id=panel.id))
            s.add(StoreProduct(store_id=main.id, product_id=product.id, is_enabled=True))
            s.add(StorePaymentConfiguration(store_id=main.id, provider="golden_gw", is_enabled=True, public_config={}))
            await s.commit()
            product_id, bundle_id = product.id, group.id
        await _admin_with_telegram(maker)

        login = await c.post(BOT_LOGIN, json=_login(main, 424242424), headers=MAIN_SECRET)
        assert login.status_code == 200 and login.json()["is_admin"] is False
        sid = login.json()["store_id"]
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

        pay = (
            await c.post(
                f"/api/v1/stores/{sid}/wallet/topups",
                json={"amount": price, "provider": "golden_gw"},
                headers={**auth, "Idempotency-Key": "adm-topup-1"},
            )
        ).json()
        async with maker() as s:
            ref = (await s.get(Payment, uuid.UUID(pay["id"]))).external_ref
        cb = await c.get(f"/api/v1/payments/callbacks/golden_gw?pid={pay['id']}&Status=OK&Authority={ref}")
        assert cb.status_code == 303
        assert (await c.get(f"/api/v1/stores/{sid}/wallet", headers=auth)).json()["balance"] == price

        body = {"product_id": str(product_id), "bundle_id": str(bundle_id), "payment_method": "wallet"}
        order = await c.post(f"/api/v1/stores/{sid}/orders", json=body, headers={**auth, "Idempotency-Key": "adm-order-1"})
        assert order.status_code == 201, order.text
        async with maker() as s:
            assert await vpn.provision_order(s, uuid.UUID(order.json()["id"])) == "completed"
            await s.commit()
        final = await c.get(f"/api/v1/stores/{sid}/orders/{order.json()['id']}", headers=auth)
        assert final.status_code == 200 and final.json()["status"] == "completed"
        accounts = await c.get(f"/api/v1/stores/{sid}/vpn-accounts", headers=auth)
        assert accounts.status_code == 200 and len(accounts.json()) == 1
