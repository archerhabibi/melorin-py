"""The admin's Telegram account is an ordinary customer in the bot; its ID is only an alert address (recognition, no rights)."""

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


async def test_the_admins_telegram_signs_in_as_a_customer_and_is_recognised():
    async with api_client() as (c, maker, main):
        admin = await add_user(maker, email="root@example.com", admin=True, totp=True)
        async with maker() as s:
            await admin_telegram.link(s, await s.get(User, admin.id), "424242424")
            await s.commit()

        r = await c.post(BOT_LOGIN, json=_login(main, 424242424), headers=MAIN_SECRET)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_admin"] is False and body["channel"] == "bot" and body["admin_alerts"] is True

        async with maker() as s:
            ident = await s.scalar(select(Identity).where(Identity.provider == "telegram", Identity.subject == "424242424"))
            assert ident is not None and ident.user_id != admin.id  # a separate customer account
            assert (await s.get(User, ident.user_id)).is_super_admin is False

        # the session is a normal customer session: it can use the store like anybody
        h = {"Authorization": f"Bearer {body['access_token']}"}
        assert (await c.get(f"/api/v1/stores/{main.id}/wallet", headers=h)).status_code == 200


async def test_an_ordinary_telegram_account_is_not_flagged():
    async with api_client() as (c, maker, main):
        r = await c.post(BOT_LOGIN, json=_login(main, 555000111), headers=MAIN_SECRET)
        assert r.status_code == 200, r.text
        assert r.json()["admin_alerts"] is False
