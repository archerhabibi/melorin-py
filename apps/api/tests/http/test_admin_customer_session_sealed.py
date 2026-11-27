"""An admin account may shop as a customer (bot, store site) but that session can never re-key the account.

The customer session of an admin account is proven by a Telegram ID (or an e-mail code), never by password + TOTP. If it could set a
password, reset the 2FA secret, link an identity or unlink one, then a stolen Telegram session (SIM swap, an unlocked phone, a typo
in the install-time Telegram ID) would be a full admin-panel takeover. These tests pin the invariant from three sides:

* the concrete attack (set a password, replace the TOTP secret, log in to the panel) is refused and leaves the account untouched;
* EVERY mutating account route is sealed unless it is on a short, explicit allow-list (fail closed for routes added later);
* nothing changes for the people who are not admins, and the admin panel session itself keeps working.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from _db import make_store
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.app import app
from melorin.core import channel as ch
from melorin.core.security import decode_access_token
from melorin.kernel.models.identity import User
from melorin.kernel.models.system import SecurityEvent
from test_admin_as_customer_http import BOT_LOGIN, MAIN_SECRET, SECRETS, _admin_with_telegram, _login

pytestmark = pytest.mark.asyncio

ME = "/api/v1/me"
NEW_PASSWORD = "Attacker-Chosen-Pass-9876!"
RESELLER_SECRET = {"X-Bot-Secret": "r" * 40}

# The ONLY mutating account routes a customer session of an admin account may call: display name / locale, and the bot's "open my
# account on the website" button. Anything else that changes how the account signs in must come from the admin panel session.
ALLOWED_FOR_ADMIN_CUSTOMER = {("PATCH", "/api/v1/me"), ("POST", "/api/v1/me/web-handoff")}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(ch, "get_settings", lambda: SECRETS)


def _account_routes() -> list[tuple[str, str]]:
    """Every mutating route of the account surface (/me and /identity, not the bot-secret /internal ones), from the OpenAPI document."""
    found = []
    for path, ops in app.openapi()["paths"].items():
        if path == ME or path.startswith(f"{ME}/") or path.startswith("/api/v1/identity/"):
            found += [(m.upper(), path) for m in ops if m.upper() in MUTATING]
    return sorted(found)


async def _bot_token(c, main, tg=424242424):
    r = await c.post(BOT_LOGIN, json=_login(main, tg), headers=MAIN_SECRET)
    assert r.status_code == 200, r.text
    return r.json()["access_token"], r.json()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _err(r) -> str:
    return r.json().get("error", {}).get("code", "")


async def test_a_telegram_session_cannot_take_over_the_admin_panel_login():
    """The exact attack: Telegram ID -> set a password -> replace the TOTP secret -> log in to the panel."""
    async with api_client() as (c, maker, main):
        admin = await _admin_with_telegram(maker)
        async with maker() as s:
            before = await s.get(User, admin.id)
            snapshot = (before.password_hash, before.totp_secret_enc, before.totp_enabled)
        token, _ = await _bot_token(c, main)
        h = _h(token)

        for method, path, body in (
            ("POST", f"{ME}/password", {"password": NEW_PASSWORD}),
            ("POST", f"{ME}/2fa/setup", None),
            ("POST", f"{ME}/2fa/enable", {"code": "000000"}),
            ("POST", f"{ME}/identities/email", {"email": "evil@example.com", "code": "000000"}),
            ("POST", f"{ME}/identities/google", {"id_token": "x" * 40}),
            ("POST", f"{ME}/link-codes/telegram", None),
        ):
            r = await c.request(method, path, json=body, headers=h)
            assert r.status_code == 403 and await _err(r) == "ADMIN_USE_PANEL", (path, r.status_code, r.text)

        # nothing moved: same password hash, same TOTP secret, 2FA still on
        async with maker() as s:
            after = await s.get(User, admin.id)
            assert (after.password_hash, after.totp_secret_enc, after.totp_enabled) == snapshot
        # the real owner still gets in with the real password + the real authenticator ...
        ok = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
        assert ok.status_code == 200 and ok.json()["is_admin"] is True
        # ... and the attacker's password gets nowhere
        bad = await c.post(
            "/api/v1/auth/password/login", json={"email": "root@example.com", "password": NEW_PASSWORD, "totp_code": totp_now(1)}
        )
        assert bad.status_code == 401


async def test_every_account_route_that_re_keys_the_account_is_sealed_for_the_admins_customer_session():
    routes = _account_routes()
    sealed = [r for r in routes if r not in ALLOWED_FOR_ADMIN_CUSTOMER]
    assert ALLOWED_FOR_ADMIN_CUSTOMER <= set(routes) and len(sealed) >= 15  # the enumeration really sees the surface (not vacuous)
    async with api_client() as (c, maker, main):
        await _admin_with_telegram(maker)
        token, _ = await _bot_token(c, main)
        leaks = []
        for method, path in sealed:
            r = await c.request(method, path, json={}, headers=_h(token))
            if not (r.status_code == 403 and await _err(r) == "ADMIN_USE_PANEL"):
                leaks.append((method, path, r.status_code))
        assert not leaks, f"routes reachable by an admin account's customer session (add CredentialUser, or allow-list on purpose): {leaks}"


async def test_the_same_routes_still_work_for_everybody_who_is_not_an_admin():
    async with api_client() as (c, maker, main):
        await add_user(maker, email="cust@example.com")
        r = await c.post(BOT_LOGIN, json=_login(main, 777000111), headers=MAIN_SECRET)
        assert r.status_code == 200 and r.json()["admin_account"] is False
        # a Telegram-only customer has no e-mail yet: the guard must not be what stops this (EMAIL_REQUIRED is the business rule)
        pw = await c.post(f"{ME}/password", json={"password": NEW_PASSWORD}, headers=_h(r.json()["access_token"]))
        assert await _err(pw) != "ADMIN_USE_PANEL"
        for method, path in _account_routes():
            if (method, path) in ALLOWED_FOR_ADMIN_CUSTOMER:
                continue
            resp = await c.request(method, path, json={}, headers=_h(r.json()["access_token"]))
            assert not (resp.status_code == 403 and await _err(resp) == "ADMIN_USE_PANEL"), (method, path)


async def test_the_admin_panel_session_can_still_change_its_own_credentials():
    async with api_client() as (c, maker, _):
        await add_user(maker, email="root@example.com", admin=True, totp=True)
        login = await c.post(
            "/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()}
        )
        assert login.status_code == 200 and login.json()["is_admin"] is True
        r = await c.post(f"{ME}/password", json={"password": NEW_PASSWORD}, headers=_h(login.json()["access_token"]))
        assert r.status_code == 200, r.text


async def test_me_reports_what_this_session_may_do_not_just_what_the_account_is():
    async with api_client() as (c, maker, main):
        await _admin_with_telegram(maker)
        token, _ = await _bot_token(c, main)
        as_customer = (await c.get(ME, headers=_h(token))).json()
        assert as_customer["is_admin"] is False and as_customer["admin_account"] is True  # the account is an admin's, the session is not
        panel = (
            await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
        ).json()
        as_admin = (await c.get(ME, headers=_h(panel["access_token"]))).json()
        assert as_admin["is_admin"] is True and as_admin["admin_account"] is True
        await add_user(maker, email="plain@example.com")
        plain = await c.post(BOT_LOGIN, json=_login(main, 123123123), headers=MAIN_SECRET)
        me = (await c.get(ME, headers=_h(plain.json()["access_token"]))).json()
        assert me["is_admin"] is False and me["admin_account"] is False
        # display name and locale stay editable from the customer session
        r = await c.patch(ME, json={"display_name": "Boss"}, headers=_h(token))
        assert r.status_code == 200 and r.json()["display_name"] == "Boss" and r.json()["is_admin"] is False


async def test_an_admin_account_never_gets_a_session_in_a_resellers_bot():
    async with api_client() as (c, maker, main):
        await _admin_with_telegram(maker)
        async with maker() as s:
            shop = await make_store(s, kind="reseller", slug="shop")
            await s.commit()
        r = await c.post(
            BOT_LOGIN, json={"telegram_id": 424242424, "first_name": "Admin", "store_id": str(shop.id)}, headers=RESELLER_SECRET
        )
        assert r.status_code == 403 and await _err(r) == "ADMIN_USE_PANEL", r.text
        # the main bot is where the admin shops
        ok = await c.post(BOT_LOGIN, json=_login(main, 424242424), headers=MAIN_SECRET)
        assert ok.status_code == 200 and decode_access_token(ok.json()["access_token"])["sid"] == str(main.id)


async def test_a_refused_re_key_attempt_is_visible_in_the_security_log():
    async with api_client() as (c, maker, main):
        admin = await _admin_with_telegram(maker)
        token, _ = await _bot_token(c, main)
        await c.post(f"{ME}/2fa/setup", headers=_h(token))
        async with maker() as s:
            events = (await s.scalars(select(SecurityEvent).where(SecurityEvent.kind == "admin_credential_change_refused"))).all()
            assert len(events) == 1 and events[0].user_id == admin.id
            assert events[0].data["path"] == f"{ME}/2fa/setup" and events[0].data["channel"] == "bot"
