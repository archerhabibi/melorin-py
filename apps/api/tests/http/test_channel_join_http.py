"""Mandatory channel membership over HTTP: the admin editor (admin-only, validated, audited, probe) and the gate at the main
bot's sign-in (refuses with CHANNEL_JOIN_REQUIRED, keeps the sign-up and its referral, fails open, never gates reseller bots)."""

from __future__ import annotations

import types

import pytest
from sqlalchemy import select

from _db import make_store, make_user
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.channels.telegram.bot_api import TelegramApiError
from melorin.core import channel as ch
from melorin.kernel.models.identity import Identity
from melorin.kernel.models.system import AuditEvent
from melorin.modules.channel_gate import service as gate

pytestmark = pytest.mark.asyncio

AUTH = "/api/v1/auth"
URL = "/api/v1/admin/telegram/channel-join"
BOT_LOGIN = f"{AUTH}/telegram/bot"
MAIN_SECRET = {"X-Bot-Secret": "m" * 40}
RESELLER_SECRET = {"X-Bot-Secret": "r" * 40}
CHANNELS = [
    {"chat": "@melorin_news", "title": "اخبار ملورین"},
    {"chat": "-1001234567890", "title": "VIP", "url": "https://t.me/+AbCdEfGh123"},
]

SECRETS = types.SimpleNamespace(
    is_dev=False,
    trusted_proxy_ips=["172.28.0.0/16"],
    store_web_url="https://main.example.com",
    public_api_url="https://main.example.com",
    bot_service_secret="s" * 40,
    main_bot_secret="m" * 40,
    reseller_bot_secret="r" * 40,
)


class FakeTelegram:
    """Answers getChatMember from a {(chat, user): status | TelegramApiError} table; the bot (id 1) admins every channel."""

    def __init__(self):
        self.members: dict[tuple[str, int], object] = {}
        self.calls = 0

    async def get_me(self):
        return {"id": 1, "username": "melorin_bot"}

    async def get_chat(self, chat):
        if chat == "@ghost_channel":
            raise TelegramApiError(400, "Bad Request: chat not found")
        return {"title": f"T {chat}", "type": "channel"}

    async def get_chat_member(self, chat, user_id):
        self.calls += 1
        if user_id == 1:
            return {"status": "member" if chat == "@not_admin_ch" else "administrator"}
        answer = self.members.get((chat, user_id), "left")
        if isinstance(answer, Exception):
            raise answer
        return {"status": answer}


@pytest.fixture
def tg(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(ch, "get_settings", lambda: SECRETS)
    monkeypatch.setattr(gate, "_channel", lambda token: fake)

    async def token(_session):
        return "123:fake"

    monkeypatch.setattr(gate, "main_bot_token", token)
    gate.clear_cache()
    yield fake
    gate.clear_cache()


async def _admin(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post(f"{AUTH}/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _login(main, telegram_id=77, **extra):
    return {"telegram_id": telegram_id, "first_name": "Ali", "store_id": str(main.id), **extra}


# ---------------------------------------------------------------------------------------------------- admin editor
async def test_editor_is_admin_only_defaults_to_off_and_saves_with_an_audit_row(tg):
    async with api_client() as (c, maker, _main):
        assert (await c.get(URL)).status_code == 401
        assert (await c.put(URL, json={"enabled": True, "channels": CHANNELS})).status_code == 401
        h = await _admin(c, maker)
        body = (await c.get(URL, headers=h)).json()
        assert body["config"]["enabled"] is False and body["config"]["channels"] == []
        assert body["limits"]["max_channels"] == 5

        r = await c.put(URL, json={"enabled": True, "channels": CHANNELS, "cache_seconds": 120}, headers=h)
        assert r.status_code == 200, r.text
        cfg = r.json()["config"]
        assert cfg["enabled"] is True and cfg["cache_seconds"] == 120
        assert cfg["channels"][0] == {"chat": "@melorin_news", "title": "اخبار ملورین", "url": "https://t.me/melorin_news"}
        assert (await c.get(URL, headers=h)).json()["config"] == cfg
        async with maker() as s:
            actions = (await s.scalars(select(AuditEvent.action))).all()
        assert "integration.telegram.channel_join.updated" in actions


async def test_invalid_submission_is_refused_and_changes_nothing(tg):
    async with api_client() as (c, maker, _main):
        h = await _admin(c, maker)
        r = await c.put(URL, json={"enabled": True, "channels": []}, headers=h)
        assert r.status_code == 422 and r.json()["error"]["code"] == "CHANNEL_JOIN_INVALID"
        r = await c.put(URL, json={"enabled": True, "channels": [{"chat": "-1001234567890"}]}, headers=h)
        assert r.status_code == 422 and "لینک دعوت" in r.json()["error"]["message"]
        assert (await c.get(URL, headers=h)).json()["config"]["enabled"] is False


async def test_check_reports_each_channel_problem(tg):
    async with api_client() as (c, maker, _main):
        h = await _admin(c, maker)
        chans = [{"chat": "@melorin_news"}, {"chat": "@not_admin_ch"}, {"chat": "@ghost_channel"}]
        r = await c.post(f"{URL}/check", json={"enabled": False, "channels": chans}, headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is False and data["bot_username"] == "melorin_bot"
        ok, not_admin, ghost = data["channels"]
        assert ok["ok"] is True and ok["problem"] is None
        assert not_admin["ok"] is False and "ادمین" in not_admin["problem"]
        assert ghost["ok"] is False and "پیدا نشد" in ghost["problem"]


# ---------------------------------------------------------------------------------------------------- the gate
async def _enable(c, maker, channels=CHANNELS):
    h = await _admin(c, maker)
    r = await c.put(URL, json={"enabled": True, "channels": channels}, headers=h)
    assert r.status_code == 200, r.text


async def test_gate_off_lets_everybody_in_without_calling_telegram(tg):
    async with api_client() as (c, _maker, main):
        r = await c.post(BOT_LOGIN, json=_login(main), headers=MAIN_SECRET)
        assert r.status_code == 200, r.text
        assert tg.calls == 0


async def test_non_member_is_refused_with_the_missing_channels_but_the_signup_is_kept(tg):
    async with api_client() as (c, maker, main):
        await _enable(c, maker)
        tg.members[("@melorin_news", 77)] = "member"  # joined the first channel only
        r = await c.post(BOT_LOGIN, json=_login(main), headers=MAIN_SECRET)
        assert r.status_code == 403, r.text
        err = r.json()["error"]
        assert err["code"] == "CHANNEL_JOIN_REQUIRED"
        assert err["details"]["channels"] == [{"title": "VIP", "url": "https://t.me/+AbCdEfGh123"}]  # never the numeric id
        assert "-100" not in r.text
        async with maker() as s:
            assert (
                await s.scalar(select(Identity).where(Identity.provider == "telegram", Identity.subject == "77")) is not None
            )  # sign-up kept


async def test_joining_opens_the_session_at_once_and_the_answer_is_cached(tg):
    async with api_client() as (c, maker, main):
        await _enable(c, maker)
        assert (await c.post(BOT_LOGIN, json=_login(main), headers=MAIN_SECRET)).status_code == 403
        tg.members[("@melorin_news", 77)] = "member"
        tg.members[("-1001234567890", 77)] = "restricted"  # restricted without is_member: no longer in the chat
        assert (await c.post(BOT_LOGIN, json=_login(main), headers=MAIN_SECRET)).status_code == 403
        tg.members[("-1001234567890", 77)] = "administrator"
        r = await c.post(BOT_LOGIN, json=_login(main), headers=MAIN_SECRET)  # negative answers were not cached
        assert r.status_code == 200 and r.json()["access_token"]
        calls = tg.calls
        assert (await c.post(BOT_LOGIN, json=_login(main), headers=MAIN_SECRET)).status_code == 200
        assert tg.calls == calls  # positive answer remembered
        tg.members[("@melorin_news", 77)] = "left"
        gate.clear_cache()
        assert (await c.post(BOT_LOGIN, json=_login(main), headers=MAIN_SECRET)).status_code == 403  # left again


async def test_an_unreadable_channel_fails_open_but_a_definite_no_still_refuses(tg):
    async with api_client() as (c, maker, main):
        await _enable(c, maker)
        tg.members[("@melorin_news", 77)] = "member"
        tg.members[("-1001234567890", 77)] = TelegramApiError(400, "Bad Request: member list is inaccessible")
        assert (await c.post(BOT_LOGIN, json=_login(main), headers=MAIN_SECRET)).status_code == 200
        gate.clear_cache()
        tg.members[("@melorin_news", 77)] = "kicked"
        tg.members[("-1001234567890", 77)] = TelegramApiError(502, "Bad Gateway")
        r = await c.post(BOT_LOGIN, json=_login(main), headers=MAIN_SECRET)
        assert r.status_code == 403 and r.json()["error"]["details"]["channels"] == [
            {"title": "اخبار ملورین", "url": "https://t.me/melorin_news"}
        ]


async def test_reseller_bots_are_never_gated(tg):
    async with api_client() as (c, maker, _main):
        await _enable(c, maker)
        async with maker() as s:
            owner = await make_user(s)
            shop = await make_store(s, kind="reseller", owner=owner, slug="shop-a")
            await s.commit()
        r = await c.post(BOT_LOGIN, json={"telegram_id": 78, "first_name": "B", "store_id": str(shop.id)}, headers=RESELLER_SECRET)
        assert r.status_code == 200, r.text
        assert tg.calls == 0


async def test_admin_message_is_what_the_user_sees(tg):
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        await c.put(URL, json={"enabled": True, "channels": CHANNELS[:1], "message": "اول عضو کانال شو 🙏"}, headers=h)
        r = await c.post(BOT_LOGIN, json=_login(main), headers=MAIN_SECRET)
        assert r.status_code == 403 and r.json()["error"]["message"] == "اول عضو کانال شو 🙏"
