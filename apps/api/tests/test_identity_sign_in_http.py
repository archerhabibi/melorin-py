"""Phase 4: /auth sign-in routes end to end over HTTP (email code, password+TOTP, refresh rotation, logout, Google, Telegram).

These pin the security behaviour of the login surface: one error for unknown user and wrong password (no enumeration),
per-account throttling, the admin second factor with replay protection, refresh-token theft detection, and the rule that a
customer channel can never mint an admin session."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core import integrations
from melorin.core.security import decode_access_token
from melorin.kernel.models.identity import RefreshToken, User
from melorin.kernel.models.stores import Store
from melorin.modules.identity import google as google_signin
from melorin.modules.identity import service
from melorin.modules.identity.routes._common import GOOGLE_NONCE_COOKIE, REFRESH_COOKIE

API = "/api/v1/auth"


def _err(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


# --- e-mail code ---------------------------------------------------------------------------------------------------


async def test_email_code_login_creates_a_site_session_bound_to_the_main_store():
    async with api_client() as (c, maker, main):
        r = await c.post(f"{API}/email/request-code", json={"email": "New@Example.com"})
        assert r.status_code == 200 and r.json()["sent"] is True
        code = r.json()["dev_code"]  # development only: production never returns the code
        r = await c.post(f"{API}/email/verify-code", json={"email": "new@example.com", "code": code})
        assert r.status_code == 200, r.text
        pair = r.json()
        assert pair["channel"] == "site" and pair["store_id"] == str(main.id) and pair["is_admin"] is False
        claims = decode_access_token(pair["access_token"])
        assert claims["chn"] == "site" and claims["sid"] == str(main.id)
        cookie = r.headers["set-cookie"]
        assert REFRESH_COOKIE in cookie and "HttpOnly" in cookie and "Path=/api/v1/auth" in cookie
        async with maker() as s:
            assert (await s.scalar(select(User).where(User.email == "new@example.com"))) is not None


async def test_email_code_rejects_wrong_codes_and_a_code_cannot_be_reused():
    async with api_client() as (c, _, _):
        code = (await c.post(f"{API}/email/request-code", json={"email": "a@example.com"})).json()["dev_code"]
        wrong = "000000" if code != "000000" else "111111"
        bad = await c.post(f"{API}/email/verify-code", json={"email": "a@example.com", "code": wrong})
        assert bad.status_code == 400 and _err(bad) == "CODE_INVALID"
        ok = await c.post(f"{API}/email/verify-code", json={"email": "a@example.com", "code": code})
        assert ok.status_code == 200
        again = await c.post(f"{API}/email/verify-code", json={"email": "a@example.com", "code": code})
        assert again.status_code == 400 and _err(again) == "CODE_INVALID"


async def test_email_code_for_an_admin_account_is_refused_on_the_customer_channel():
    async with api_client() as (c, maker, _):
        await add_user(maker, email="root@example.com", admin=True, totp=True)
        code = (await c.post(f"{API}/email/request-code", json={"email": "root@example.com"})).json()["dev_code"]
        r = await c.post(f"{API}/email/verify-code", json={"email": "root@example.com", "code": code})
        assert r.status_code == 403 and _err(r) == "ADMIN_USE_PANEL"


async def test_malformed_input_gets_the_validation_envelope():
    async with api_client() as (c, _, _):
        r = await c.post(f"{API}/email/request-code", json={"email": "not-an-email"})
        assert r.status_code == 422 and _err(r) == "VALIDATION_ERROR"


# --- password + TOTP -----------------------------------------------------------------------------------------------


async def test_password_login_succeeds_for_a_customer_and_binds_the_site_channel():
    async with api_client() as (c, maker, main):
        await add_user(maker)
        r = await c.post(f"{API}/password/login", json={"email": " USER@example.com ", "password": PASSWORD})
        assert r.status_code == 200, r.text
        assert (r.json()["channel"], r.json()["store_id"], r.json()["is_admin"]) == ("site", str(main.id), False)


async def test_wrong_password_and_unknown_user_are_indistinguishable_and_inactive_accounts_cannot_log_in():
    async with api_client() as (c, maker, _):
        await add_user(maker)
        await add_user(maker, email="off@example.com", active=False)
        responses = [
            await c.post(f"{API}/password/login", json={"email": "user@example.com", "password": "wrong-password-1"}),
            await c.post(f"{API}/password/login", json={"email": "ghost@example.com", "password": "wrong-password-1"}),
            await c.post(f"{API}/password/login", json={"email": "off@example.com", "password": PASSWORD}),
        ]
        assert {(r.status_code, _err(r), r.json()["error"]["message"]) for r in responses} == {
            (401, "INVALID_CREDENTIALS", responses[0].json()["error"]["message"])
        }


async def test_repeated_failures_throttle_the_account_even_with_the_right_password():
    async with api_client() as (c, maker, _):
        await add_user(maker)
        for _ in range(10):
            await c.post(f"{API}/password/login", json={"email": "user@example.com", "password": "wrong-password-1"})
        r = await c.post(f"{API}/password/login", json={"email": "user@example.com", "password": PASSWORD})
        assert r.status_code == 429 and _err(r) == "ACCOUNT_LOGIN_THROTTLED"


async def test_admin_without_two_factor_cannot_log_in_with_a_password():
    async with api_client() as (c, maker, _):
        await add_user(maker, email="root@example.com", admin=True, totp=False)
        r = await c.post(f"{API}/password/login", json={"email": "root@example.com", "password": PASSWORD})
        assert r.status_code == 403 and _err(r) == "ADMIN_2FA_REQUIRED"


async def test_admin_login_needs_a_valid_totp_and_gets_an_unbound_admin_session():
    async with api_client() as (c, maker, _):
        await add_user(maker, email="root@example.com", admin=True, totp=True)
        body = {"email": "root@example.com", "password": PASSWORD}
        missing = await c.post(f"{API}/password/login", json=body)
        wrong = await c.post(f"{API}/password/login", json={**body, "totp_code": "12345a"})
        assert (missing.status_code, _err(missing)) == (401, "TOTP_REQUIRED") and wrong.status_code == 401
        code = totp_now()  # ONE code for both attempts: two totp_now() calls can straddle a 30 s step boundary and flake
        ok = await c.post(f"{API}/password/login", json={**body, "totp_code": code})
        assert ok.status_code == 200, ok.text
        assert (ok.json()["is_admin"], ok.json()["channel"], ok.json()["store_id"]) == (True, "admin", None)
        replay = await c.post(f"{API}/password/login", json={**body, "totp_code": code})
        assert replay.status_code == 401 and _err(replay) == "TOTP_REQUIRED"  # the same 30 s step cannot be used twice


async def test_customer_with_totp_enabled_must_also_present_a_code():
    async with api_client() as (c, maker, _):
        await add_user(maker, totp=True)
        body = {"email": "user@example.com", "password": PASSWORD}
        assert (await c.post(f"{API}/password/login", json=body)).status_code == 401
        assert (await c.post(f"{API}/password/login", json={**body, "totp_code": totp_now()})).status_code == 200


# --- refresh / logout ----------------------------------------------------------------------------------------------


async def _login(c, maker):
    await add_user(maker)
    r = await c.post(f"{API}/password/login", json={"email": "user@example.com", "password": PASSWORD})
    return r.json()


async def test_refresh_rotates_the_token_and_reuse_of_the_old_one_revokes_the_whole_family():
    async with api_client() as (c, maker, _):
        first = await _login(c, maker)
        c.cookies.clear()
        second = await c.post(f"{API}/refresh", json={"refresh_token": first["refresh_token"]})
        assert second.status_code == 200 and second.json()["refresh_token"] != first["refresh_token"]
        assert second.json()["store_id"] == first["store_id"]  # a refresh can never move the session to another store
        theft = await c.post(f"{API}/refresh", json={"refresh_token": first["refresh_token"]})
        assert theft.status_code == 401 and _err(theft) == "INVALID_REFRESH"
        c.cookies.clear()
        victim = await c.post(f"{API}/refresh", json={"refresh_token": second.json()["refresh_token"]})
        assert victim.status_code == 401  # the legitimate holder is logged out too: the family is burned
        async with maker() as s:
            assert all(t.revoked_at for t in (await s.scalars(select(RefreshToken))).all())


async def test_refresh_accepts_the_httponly_cookie_and_rejects_missing_or_garbage_tokens():
    async with api_client() as (c, maker, _):
        await _login(c, maker)  # the client now holds the refresh cookie
        assert (await c.post(f"{API}/refresh", json={})).status_code == 200
        c.cookies.clear()
        none = await c.post(f"{API}/refresh", json={})
        assert none.status_code == 401 and _err(none) == "INVALID_REFRESH"
        bad = await c.post(f"{API}/refresh", json={"refresh_token": "garbage"})
        assert bad.status_code == 401


async def test_logout_revokes_the_refresh_token_and_clears_the_cookie():
    async with api_client() as (c, maker, _):
        pair = await _login(c, maker)
        out = await c.post(f"{API}/logout", json={"refresh_token": pair["refresh_token"]})
        assert out.status_code == 200 and out.json() == {"ok": True}
        assert REFRESH_COOKIE in out.headers["set-cookie"]
        c.cookies.clear()
        assert (await c.post(f"{API}/refresh", json={"refresh_token": pair["refresh_token"]})).status_code == 401
        assert (await c.post(f"{API}/logout", json={})).status_code == 200  # idempotent without a token


# --- Google ---------------------------------------------------------------------------------------------------------


async def test_google_config_is_public_and_not_cacheable():
    async with api_client() as (c, _, _):
        r = await c.get(f"{API}/google/config")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        assert set(r.json()) == {"enabled", "client_id", "admin_login", "store_login"}


async def test_google_nonce_is_fresh_single_purpose_and_httponly():
    async with api_client() as (c, _, _):
        a, b = (await c.get(f"{API}/google/nonce")).json()["nonce"], (await c.get(f"{API}/google/nonce")).json()["nonce"]
        r = await c.get(f"{API}/google/nonce")
        assert a != b and len(a) >= 24 and r.headers["cache-control"] == "no-store"
        cookie = r.headers["set-cookie"]
        assert GOOGLE_NONCE_COOKIE in cookie and "HttpOnly" in cookie and "Path=/api/v1/auth/google" in cookie


@pytest.fixture
def google(monkeypatch):
    state = {"user": None, "created": False, "cfg": {"admin_login": True, "store_login": True}, "seen": []}

    async def fake_login(session, token, nonce):
        state["seen"].append((token, nonce))
        return await session.get(User, state["user"].id), state["created"]

    async def fake_cfg(session):
        return state["cfg"]

    monkeypatch.setattr(google_signin, "login_with_google", fake_login)
    monkeypatch.setattr(integrations, "get_google", fake_cfg)
    return state


async def test_google_customer_login_passes_the_nonce_cookie_and_consumes_it(google):
    async with api_client() as (c, maker, main):
        google["user"] = await add_user(maker, password=None)
        c.cookies.set(GOOGLE_NONCE_COOKIE, "nonce-123", path="/api/v1/auth/google")
        r = await c.post(f"{API}/google", json={"id_token": "tok"})
        assert r.status_code == 200, r.text
        assert r.json()["store_id"] == str(main.id) and google["seen"] == [("tok", "nonce-123")]
        assert f'{GOOGLE_NONCE_COOKIE}="";' in r.headers.get_list("set-cookie")[-1] or GOOGLE_NONCE_COOKIE in r.headers["set-cookie"]


@pytest.mark.parametrize(
    "admin, cfg, code",
    [
        (False, {"admin_login": True, "store_login": False}, "GOOGLE_STORE_DISABLED"),
        (True, {"admin_login": False, "store_login": True}, "GOOGLE_ADMIN_DISABLED"),
    ],
)
async def test_google_login_respects_the_per_audience_switches(google, admin, cfg, code):
    async with api_client() as (c, maker, _):
        google["user"], google["cfg"] = await add_user(maker, admin=admin, totp=admin), cfg
        r = await c.post(f"{API}/google", json={"id_token": "tok"})
        assert r.status_code == 403 and _err(r) == code


async def test_google_never_bypasses_the_admin_second_factor(google):
    async with api_client() as (c, maker, _):
        google["user"] = await add_user(maker, admin=True, totp=True)
        no_code = await c.post(f"{API}/google", json={"id_token": "tok"})
        assert no_code.status_code == 401 and _err(no_code) == "TOTP_REQUIRED"
        code = totp_now()  # same code twice (see the password-login replay test)
        ok = await c.post(f"{API}/google", json={"id_token": "tok", "totp_code": code})
        assert ok.status_code == 200 and ok.json()["channel"] == "admin" and ok.json()["is_admin"] is True
        replay = await c.post(f"{API}/google", json={"id_token": "tok", "totp_code": code})
        assert replay.status_code == 401


async def test_google_admin_without_totp_enrolment_is_refused(google):
    async with api_client() as (c, maker, _):
        google["user"] = await add_user(maker, admin=True, totp=False)
        r = await c.post(f"{API}/google", json={"id_token": "tok", "totp_code": "123456"})
        assert r.status_code == 403 and _err(r) == "ADMIN_2FA_REQUIRED"


# --- Telegram -------------------------------------------------------------------------------------------------------


@pytest.fixture
def tg_profile(monkeypatch):
    monkeypatch.setattr(service, "verify_telegram_webapp", lambda init, token: {"id": 777, "first_name": "Ali", "username": "ali"})
    monkeypatch.setattr(
        "melorin.modules.identity.routes.sign_in.get_settings", lambda: type("S", (), {"main_bot_token": "MAIN", "is_dev": True})()
    )


async def test_telegram_webapp_signs_in_through_the_main_bot_and_binds_that_store(tg_profile):
    async with api_client() as (c, maker, main):
        r = await c.post(f"{API}/telegram/webapp", json={"init_data": "x"})
        assert r.status_code == 200, r.text
        assert (r.json()["channel"], r.json()["store_id"]) == ("bot", str(main.id))


async def test_telegram_webapp_refuses_unknown_inactive_or_tokenless_stores(tg_profile):
    import uuid

    async with api_client() as (c, maker, main):
        unknown = await c.post(f"{API}/telegram/webapp", json={"init_data": "x", "store_id": str(uuid.uuid4())})
        assert unknown.status_code == 400 and _err(unknown) == "TELEGRAM_DISABLED"
        async with maker() as s:
            reseller = Store(kind="reseller", name="r", slug="r1", currency="IRT", status="active")  # no bot token of its own
            s.add(reseller)
            await s.commit()
        tokenless = await c.post(f"{API}/telegram/webapp", json={"init_data": "x", "store_id": str(reseller.id)})
        assert tokenless.status_code == 400 and _err(tokenless) == "TELEGRAM_DISABLED"  # never falls back to the main bot's token
        async with maker() as s:
            (await s.get(Store, main.id)).status = "suspended"
            await s.commit()
        inactive = await c.post(f"{API}/telegram/webapp", json={"init_data": "x"})
        assert inactive.status_code == 400


async def test_telegram_webapp_never_mints_an_admin_session(tg_profile, monkeypatch):
    async with api_client() as (c, maker, _):
        admin = await add_user(maker, email="root@example.com", admin=True, totp=True)

        async def as_admin(session, profile):
            return await session.get(User, admin.id), False

        monkeypatch.setattr(service, "login_with_telegram", as_admin)
        r = await c.post(f"{API}/telegram/webapp", json={"init_data": "x"})
        assert r.status_code == 403 and _err(r) == "ADMIN_USE_PANEL"


async def test_web_handoff_redeem_issues_a_session_for_the_user_the_bot_vouched_for(monkeypatch):
    async with api_client() as (c, maker, main):
        user = await add_user(maker)
        seen = {}

        async def redeem(session, token, site):
            seen["args"] = (token, site.store_id)
            return await session.get(User, user.id)

        monkeypatch.setattr(service, "redeem_web_handoff", redeem)
        r = await c.post(f"{API}/web-handoff/redeem", json={"token": "t" * 32})
        assert r.status_code == 200 and seen["args"] == ("t" * 32, main.id)
        assert (await c.post(f"{API}/web-handoff/redeem", json={"token": "short"})).status_code == 422
