"""Admin button-style editor over HTTP: admin-only, validated, audited, and the public projection the bots download."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from _http import PASSWORD, add_user, api_client, totp_now
from melorin.kernel.models.system import AuditEvent

pytestmark = pytest.mark.asyncio

AUTH = "/api/v1/auth"
URL = "/api/v1/admin/telegram/button-styles"
PUBLIC = "/api/v1/telegram/button-styles"
RULES = [
    {"kind": "inline", "match": "prefix", "key": "buy:", "style": "success", "prefix": "💎 "},
    {"kind": "reply", "key": "🛒 خرید اکانت", "style": "primary", "icon": "5368324170671202286"},
]


async def _admin(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post(f"{AUTH}/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_editor_requires_admin_and_defaults_to_off():
    async with api_client() as (c, maker, _):
        assert (await c.get(URL)).status_code == 401
        assert (await c.put(URL, json={"enabled": True, "rules": RULES})).status_code == 401
        h = await _admin(c, maker)
        body = (await c.get(URL, headers=h)).json()
        assert body["config"] == {"enabled": False, "rules": []}
        assert {p["id"] for p in body["presets"]} == {"classic", "premium", "calm"}
        assert any(i["key"] == "menu:plans" for i in body["catalog"])
        assert (await c.get(PUBLIC)).json() == {"enabled": False, "inline": [], "reply": []}


async def test_save_publishes_to_bots_and_writes_an_audit_row():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        r = await c.put(URL, json={"enabled": True, "rules": RULES}, headers=h)
        assert r.status_code == 200, r.text
        pub = await c.get(PUBLIC)  # no credentials: the bots need none and nothing secret is in it
        assert pub.status_code == 200 and "max-age" in pub.headers["cache-control"]
        data = pub.json()
        assert data["enabled"] is True
        assert data["inline"] == [{"key": "buy:", "match": "prefix", "style": "success", "prefix": "💎 "}]
        assert data["reply"] == [{"key": "🛒 خرید اکانت", "match": "exact", "style": "primary", "icon": "5368324170671202286"}]
        async with maker() as s:
            actions = (await s.scalars(select(AuditEvent.action))).all()
        assert "integration.telegram.button_styles.updated" in actions


async def test_invalid_submission_is_refused_and_changes_nothing():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        await c.put(URL, json={"enabled": True, "rules": RULES}, headers=h)
        r = await c.put(URL, json={"enabled": True, "rules": [{"kind": "inline", "key": "x:", "style": "purple"}]}, headers=h)
        assert r.status_code == 422
        assert "BUTTON_STYLE_INVALID" in r.text
        assert (await c.get(URL, headers=h)).json()["config"]["rules"][0]["key"] == "buy:"


async def test_preview_needs_a_telegram_id_for_the_admin():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        r = await c.post(f"{URL}/preview", json={"enabled": True, "rules": RULES}, headers=h)
        assert r.status_code == 409 and "ADMIN_TELEGRAM_MISSING" in r.text


async def test_generic_settings_api_cannot_overwrite_the_integration_key():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        r = await c.put("/api/v1/admin/settings/integration.telegram_button_styles", json={"value": {"enabled": True}}, headers=h)
        assert r.status_code == 400


@pytest.mark.parametrize(
    ("code", "expected_code", "status"),
    [
        (403, "TELEGRAM_CHAT_UNREACHABLE", 409),
        (401, "MAIN_BOT_TOKEN_INVALID", 409),
        (429, "TELEGRAM_RATE_LIMITED", 429),
        (599, "TELEGRAM_UNREACHABLE", 502),
        (502, "TELEGRAM_UNREACHABLE", 502),
        (404, "MAIN_BOT_TOKEN_INVALID", 409),
        (400, "TELEGRAM_REJECTED_STYLE", 422),
    ],
)
async def test_preview_failure_blames_the_real_cause(code, expected_code, status):
    """Only a 400 is Telegram refusing the style; a blocked bot / bad token / flood-wait / outage must not read like a bad emoji."""
    from melorin.channels.telegram.bot_api import TelegramApiError
    from melorin.modules.admin.button_styles import _telegram_failure

    err = _telegram_failure(TelegramApiError(code, "Forbidden: bot can't initiate conversation with a user"))
    assert (err.code, err.status) == (expected_code, status)


@pytest.mark.parametrize("description", ["Bad Request: chat not found", "Bad Request: user not found", "Bad Request: PEER_ID_INVALID"])
async def test_preview_400_about_the_chat_is_not_blamed_on_the_style(description):
    """A wrong / never-started admin chat id is a 400 too; it must not read like a bad Premium emoji."""
    from melorin.channels.telegram.bot_api import TelegramApiError
    from melorin.modules.admin.button_styles import _telegram_failure

    err = _telegram_failure(TelegramApiError(400, description))
    assert (err.code, err.status) == ("TELEGRAM_CHAT_UNREACHABLE", 409)
