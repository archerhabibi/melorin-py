"""Phase 4: /me (account hub) and /auth/admin/password end to end over HTTP.

Pins the account-management behaviour: profile read/update, which stores a SESSION may see (channel scoping), the Telegram
link code, the bot -> website handoff (single use, own store only, never for admins), e-mail attachment, password setting and
the TOTP enable flow, plus the admin password change guards."""

from __future__ import annotations

from sqlalchemy import select

from _db import make_store
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.security import _totp, create_access_token
from melorin.kernel.models.identity import User
from melorin.kernel.models.stores import StoreMembership

AUTH = "/api/v1/auth"
ME = "/api/v1/me"


def _err(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _site_login(c, maker, *, email="user@example.com", **kw) -> dict:
    user = await add_user(maker, email=email, **kw)
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"user": user, "headers": _bearer(r.json()["access_token"]), "pair": r.json()}


async def _member(maker, store, user, role="customer"):
    async with maker() as s:
        s.add(StoreMembership(store_id=store.id, user_id=user.id, role=role))
        await s.commit()


# --- profile ---------------------------------------------------------------------------------------------------------


async def test_me_requires_a_session():
    async with api_client() as (c, _, _):
        assert (await c.get(ME)).status_code == 401
        assert (await c.patch(ME, json={"display_name": "x"})).status_code == 401


async def test_me_returns_the_profile_and_patch_updates_only_the_fields_sent():
    async with api_client() as (c, maker, _):
        a = await _site_login(c, maker)
        me = (await c.get(ME, headers=a["headers"])).json()
        assert me["email"] == "user@example.com" and me["is_admin"] is False and me["totp_enabled"] is False
        assert me["identities"] == [] or all({"provider", "subject", "verified"} <= set(i) for i in me["identities"])
        r = await c.patch(ME, json={"display_name": "Nima"}, headers=a["headers"])
        assert r.status_code == 200 and r.json()["display_name"] == "Nima"
        async with maker() as s:
            row = await s.get(User, a["user"].id)
            assert (row.display_name, row.locale) == ("Nima", "fa")  # locale untouched: exclude_none semantics
        r = await c.patch(ME, json={"locale": "en"}, headers=a["headers"])
        assert r.status_code == 200
        async with maker() as s:
            row = await s.get(User, a["user"].id)
            assert (row.display_name, row.locale) == ("Nima", "en")


# --- visible stores (channel scoping) ------------------------------------------------------------------------------


async def test_my_stores_is_scoped_to_the_session_channel():
    async with api_client() as (c, maker, main):
        a = await _site_login(c, maker)
        async with maker() as s:
            owned = await make_store(s, kind="reseller", owner=a["user"], slug="owned")
            other = await make_store(s, kind="reseller", slug="other")
            await s.commit()
        await _member(maker, main, a["user"])
        await _member(maker, owned, a["user"], role="owner")
        await _member(maker, other, a["user"])

        # main-store (account hub) session: the main store plus the stores the user OWNS, never a mere membership
        hub = (await c.get(f"{ME}/stores", headers=a["headers"])).json()
        assert {s["slug"] for s in hub} == {main.slug, "owned"}
        assert {s["slug"]: s["role"] for s in hub}["owned"] == "owner"

        # a bot session opened for the other store sees only that store
        tok, _ = create_access_token(a["user"].id, False, store_id=other.id, channel="bot")
        only = (await c.get(f"{ME}/stores", headers=_bearer(tok))).json()
        assert [s["slug"] for s in only] == ["other"]


# --- telegram link code ---------------------------------------------------------------------------------------------


async def test_telegram_link_code_is_returned_with_a_deeplink_only_when_the_main_bot_is_known():
    async with api_client() as (c, maker, main):
        a = await _site_login(c, maker)
        r = await c.post(f"{ME}/link-codes/telegram", headers=a["headers"])
        assert r.status_code == 200
        body = r.json()
        assert body["expires_in"] == 600 and len(body["code"]) >= 9 and body["telegram_deeplink"] is None
        async with maker() as s:
            store = await s.get(type(main), main.id)
            store.bot_username = "melorin_bot"
            await s.commit()
        body = (await c.post(f"{ME}/link-codes/telegram", headers=a["headers"])).json()
        assert body["telegram_deeplink"] == f"https://t.me/melorin_bot?start=link_{body['code']}"


# --- bot -> website handoff -------------------------------------------------------------------------------------------


async def test_web_handoff_is_only_for_bot_sessions_of_their_own_store():
    async with api_client() as (c, maker, main):
        a = await _site_login(c, maker)
        async with maker() as s:
            other = await make_store(s, kind="reseller", slug="other")
            await s.commit()
        # a website session cannot ask for a handoff (it already is one)
        site = await c.post(f"{ME}/web-handoff", json={}, headers=a["headers"])
        assert site.status_code == 403 and _err(site) == "ADMIN_USE_PANEL"

        bot, _ = create_access_token(a["user"].id, False, store_id=main.id, channel="bot")
        # ... and a bot session can only hand off to ITS store
        wrong = await c.post(f"{ME}/web-handoff", json={"store_id": str(other.id)}, headers=_bearer(bot))
        assert wrong.status_code == 403 and _err(wrong) == "CHANNEL_MISMATCH"


async def test_web_handoff_url_uses_the_store_domain_and_the_token_is_single_use():
    async with api_client() as (c, maker, main):
        a = await _site_login(c, maker)
        async with maker() as s:
            store = await s.get(type(main), main.id)
            store.domain = "Shop.Example.com."
            await s.commit()
        bot, _ = create_access_token(a["user"].id, False, store_id=main.id, channel="bot")
        r = await c.post(f"{ME}/web-handoff", json={"store_id": str(main.id)}, headers=_bearer(bot))
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        assert url.startswith("https://shop.example.com/#/auth/handoff?t=") and r.json()["google_linked"] is False
        token = url.split("t=")[1]

        ok = await c.post(f"{AUTH}/web-handoff/redeem", json={"token": token})
        assert ok.status_code == 200, ok.text
        assert (ok.json()["channel"], ok.json()["store_id"]) == ("site", str(main.id))
        again = await c.post(f"{AUTH}/web-handoff/redeem", json={"token": token})
        assert again.status_code >= 400  # redeemed once: replaying the URL gets nothing


async def test_web_handoff_falls_back_to_the_configured_store_web_url_and_is_rate_limited():
    async with api_client() as (c, maker, main):
        a = await _site_login(c, maker)
        bot, _ = create_access_token(a["user"].id, False, store_id=main.id, channel="bot")
        first = await c.post(f"{ME}/web-handoff", json={}, headers=_bearer(bot))
        assert first.status_code == 200 and first.json()["url"].startswith("http://localhost:3000/#/auth/handoff?t=")
        for _ in range(9):
            assert (await c.post(f"{ME}/web-handoff", json={}, headers=_bearer(bot))).status_code == 200
        limited = await c.post(f"{ME}/web-handoff", json={}, headers=_bearer(bot))
        assert limited.status_code == 429 and _err(limited) == "RATE_LIMITED"


async def test_web_handoff_is_refused_for_admin_accounts():
    async with api_client() as (c, maker, main):
        root = await add_user(maker, email="root@example.com", admin=True, totp=True)
        bot, _ = create_access_token(root.id, False, store_id=main.id, channel="bot")
        r = await c.post(f"{ME}/web-handoff", json={}, headers=_bearer(bot))
        assert r.status_code == 403 and _err(r) == "ADMIN_USE_PANEL"


# --- e-mail identity --------------------------------------------------------------------------------------------------


async def test_attach_email_needs_a_valid_code_for_that_address():
    async with api_client() as (c, maker, _):
        a = await _site_login(c, maker, email="first@example.com")
        code = (await c.post(f"{AUTH}/email/request-code", json={"email": "second@example.com"})).json()["dev_code"]
        bad = await c.post(
            f"{ME}/identities/email",
            json={"email": "second@example.com", "code": "0" * 6 if code != "0" * 6 else "1" * 6},
            headers=a["headers"],
        )
        assert bad.status_code == 400
        ok = await c.post(f"{ME}/identities/email", json={"email": "second@example.com", "code": code}, headers=a["headers"])
        assert ok.status_code == 200 and ok.json() == {"ok": True}
        me = (await c.get(ME, headers=a["headers"])).json()
        assert any(i["provider"] == "email" and i["subject"] == "second@example.com" and i["verified"] for i in me["identities"])


# --- password ---------------------------------------------------------------------------------------------------------


async def test_set_password_needs_an_email_and_replaces_the_credential():
    async with api_client() as (c, maker, _):
        a = await _site_login(c, maker)
        short = await c.post(f"{ME}/password", json={"password": "short"}, headers=a["headers"])
        assert short.status_code == 422
        ok = await c.post(f"{ME}/password", json={"password": "a-brand-new-password-1"}, headers=a["headers"])
        assert ok.status_code == 200
        old = await c.post(f"{AUTH}/password/login", json={"email": "user@example.com", "password": PASSWORD})
        new = await c.post(f"{AUTH}/password/login", json={"email": "user@example.com", "password": "a-brand-new-password-1"})
        assert old.status_code == 401 and new.status_code == 200

        # an account with no e-mail (e.g. Telegram-only) must attach one first
        async with maker() as s:
            tg = User(display_name="tg", email=None)
            s.add(tg)
            await s.commit()
        tok, _ = create_access_token(tg.id, False, store_id=(await _main_id(maker)), channel="site")
        r = await c.post(f"{ME}/password", json={"password": "a-brand-new-password-1"}, headers=_bearer(tok))
        assert r.status_code == 400 and _err(r) == "EMAIL_REQUIRED"


async def _main_id(maker):
    from melorin.kernel.models.stores import Store

    async with maker() as s:
        return (await s.scalar(select(Store).where(Store.kind == "main"))).id


# --- TOTP -------------------------------------------------------------------------------------------------------------


async def test_totp_setup_then_enable_requires_a_real_code_and_arms_the_second_factor():
    async with api_client() as (c, maker, _):
        a = await _site_login(c, maker)
        setup = await c.post(f"{ME}/2fa/setup", headers=a["headers"])
        assert setup.status_code == 200
        secret = setup.json()["secret"]
        assert setup.json()["otpauth_url"].startswith("otpauth://totp/Melorin:user@example.com?secret=" + secret)
        async with maker() as s:
            assert (await s.get(User, a["user"].id)).totp_enabled is False  # set-up alone enables nothing

        import time

        bad = await c.post(f"{ME}/2fa/enable", json={"code": "000000"}, headers=a["headers"])
        assert bad.status_code == 400 and _err(bad) == "TOTP_INVALID"
        code = _totp(secret, int(time.time()) // 30)
        ok = await c.post(f"{ME}/2fa/enable", json={"code": code}, headers=a["headers"])
        assert ok.status_code == 200 and ok.json() == {"ok": True}
        async with maker() as s:
            row = await s.get(User, a["user"].id)
            assert row.totp_enabled is True and row.totp_last_counter == int(time.time()) // 30

        # from now on the password alone is not enough
        c.cookies.clear()
        assert (await c.post(f"{AUTH}/password/login", json={"email": "user@example.com", "password": PASSWORD})).status_code == 401


async def test_totp_enable_without_a_prior_setup_is_rejected():
    async with api_client() as (c, maker, _):
        a = await _site_login(c, maker)
        r = await c.post(f"{ME}/2fa/enable", json={"code": "123456"}, headers=a["headers"])
        assert r.status_code == 400 and _err(r) == "TOTP_INVALID"


# --- admin password -----------------------------------------------------------------------------------------------------


async def _admin_login(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post(f"{AUTH}/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return _bearer(r.json()["access_token"])


async def test_admin_password_change_guards_and_effect():
    async with api_client() as (c, maker, _):
        h = await _admin_login(c, maker)
        path = f"{AUTH}/admin/password"
        wrong = await c.post(path, json={"current_password": "not-the-password-1", "new_password": "another-strong-pass-1"}, headers=h)
        assert wrong.status_code == 401 and _err(wrong) == "INVALID_CURRENT_PASSWORD"
        same = await c.post(path, json={"current_password": PASSWORD, "new_password": PASSWORD}, headers=h)
        assert same.status_code == 400 and _err(same) == "PASSWORD_UNCHANGED"
        ok = await c.post(path, json={"current_password": PASSWORD, "new_password": "another-strong-pass-1"}, headers=h)
        assert ok.status_code == 200 and ok.json() == {"ok": True}
        c.cookies.clear()
        old = await c.post(f"{AUTH}/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now(1)})
        assert old.status_code == 401


async def test_admin_password_change_is_not_available_to_customers():
    async with api_client() as (c, maker, _):
        a = await _site_login(c, maker)
        r = await c.post(
            f"{AUTH}/admin/password",
            json={"current_password": PASSWORD, "new_password": "another-strong-pass-1"},
            headers=a["headers"],
        )
        assert r.status_code in (401, 403)
