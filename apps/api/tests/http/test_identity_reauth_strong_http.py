"""Stronger re-authentication for accounts without a password or e-mail: Google token / Telegram bot code (docs/08, docs/12)."""

from __future__ import annotations

from sqlalchemy import select

from _http import api_client
from melorin.core.security import create_access_token
from melorin.domain.account_linking import Evidence
from melorin.kernel.models.identity import Identity, User
from melorin.kernel.models.system import OutboxEvent
from melorin.modules.identity import google as google_signin
from melorin.modules.identity.account_linking import linking

ID = "/api/v1/identity"


def _err(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


def _auth(user, main):
    token, _ = create_access_token(user.id, False, store_id=main.id, channel="site")
    return {"Authorization": f"Bearer {token}"}


async def _bare_user(maker) -> User:
    async with maker() as s:
        u = User(display_name="bare", is_guest=False, is_active=True)
        s.add(u)
        await s.commit()
        return u


async def _attach(maker, user, provider, subject, evidence):
    async with maker() as s:
        u = await s.merge(user)
        await linking.attach_identity(s, u, provider, subject, evidence=evidence)
        await s.commit()
        return (await s.scalars(select(Identity).where(Identity.provider == provider, Identity.subject == subject))).one()


async def test_method_prefers_the_strongest_owned_factor():
    async with api_client() as (c, maker, main):
        tg_only = await _bare_user(maker)
        await _attach(maker, tg_only, "telegram", "1001", Evidence.TELEGRAM_BOT)
        g_only = await _bare_user(maker)
        await _attach(maker, g_only, "google", "g-1", Evidence.OAUTH_GOOGLE)
        both = await _bare_user(maker)
        await _attach(maker, both, "telegram", "1002", Evidence.TELEGRAM_BOT)
        await _attach(maker, both, "google", "g-2", Evidence.OAUTH_GOOGLE)
        nothing = await _bare_user(maker)
        got = {}
        for name, u in {"tg": tg_only, "g": g_only, "both": both, "none": nothing}.items():
            got[name] = (await c.get(f"{ID}/reauth", headers=_auth(u, main))).json()["method"]
        assert got == {"tg": "telegram_code", "g": "google", "both": "google", "none": "session"}


async def test_telegram_only_account_must_prove_the_bot_code_once():
    async with api_client() as (c, maker, main):
        user = await _bare_user(maker)
        tg = await _attach(maker, user, "telegram", "2001", Evidence.TELEGRAM_BOT)
        h = _auth(user, main)
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(tg.id)}, headers=h)
        assert r.status_code == 401 and _err(r) == "REAUTH_REQUIRED"
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(tg.id), "reauth_code": "000000"}, headers=h)
        assert _err(r) == "REAUTH_REQUIRED"
        started = await c.post(f"{ID}/reauth/telegram/start", headers=h)
        assert started.status_code == 200, started.text
        code = started.json()["dev_code"]
        async with maker() as s:
            ev = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == "notification.send"))).all()
        assert len(ev) == 1 and ev[0].payload["kind"] == "identity_reauth" and code in ev[0].payload["body"]
        # proof accepted: the request now reaches the last-sign-in-method guard, which still refuses
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(tg.id), "reauth_code": code}, headers=h)
        assert r.status_code == 409 and _err(r) == "LAST_LOGIN_METHOD"
        # single use
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(tg.id), "reauth_code": code}, headers=h)
        assert _err(r) == "REAUTH_REQUIRED"


async def test_telegram_code_start_is_refused_for_other_account_types():
    async with api_client() as (c, maker, main):
        user = await _bare_user(maker)
        await _attach(maker, user, "google", "g-9", Evidence.OAUTH_GOOGLE)
        r = await c.post(f"{ID}/reauth/telegram/start", headers=_auth(user, main))
        assert r.status_code == 400 and _err(r) == "REAUTH_NOT_APPLICABLE"


async def test_google_only_account_needs_a_fresh_token_of_its_own_google_login(monkeypatch):
    async with api_client() as (c, maker, main):
        user = await _bare_user(maker)
        g1 = await _attach(maker, user, "google", "g-own-1", Evidence.OAUTH_GOOGLE)
        await _attach(maker, user, "google", "g-own-2", Evidence.OAUTH_GOOGLE)
        h = _auth(user, main)

        async def fake_claims(session, token, nonce):
            if token == "bad":
                raise google_signin.AppError("GOOGLE_INVALID", "x", 401)
            return {"sub": {"own": "g-own-2", "foreign": "g-stranger"}[token]}

        monkeypatch.setattr(google_signin, "google_claims", fake_claims)
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(g1.id)}, headers=h)
        assert r.status_code == 401 and _err(r) == "REAUTH_REQUIRED"
        for token in ("bad", "foreign"):
            r = await c.post(f"{ID}/unlink", json={"identity_id": str(g1.id), "google_id_token": token}, headers=h)
            assert r.status_code == 401 and _err(r) == "REAUTH_REQUIRED", token
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(g1.id), "google_id_token": "own"}, headers=h)
        assert r.status_code == 200 and r.json()["status"] == "revoked"


async def test_a_revoked_telegram_never_receives_notifications(monkeypatch):
    from melorin.core.config import get_settings
    from melorin.modules.notifications.dispatch import telegram_target

    async with api_client() as (_c, maker, _main):
        user = await _bare_user(maker)
        tg = await _attach(maker, user, "telegram", "3001", Evidence.TELEGRAM_BOT)
        settings = get_settings()
        monkeypatch.setattr(settings, "main_bot_token", "123:abc", raising=False)
        async with maker() as s:
            assert await telegram_target(s, user.id, None, settings) is not None
            ident = await s.get(Identity, tg.id)
            ident.status = "revoked"
            await s.commit()
            assert await telegram_target(s, user.id, None, settings) is None
