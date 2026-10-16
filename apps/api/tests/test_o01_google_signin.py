"""Google Sign-In: the endpoint must keep the same guarantees as the other login paths (admin 2FA, refresh cookie, CSP, build args)."""
import time
import types
from pathlib import Path

import pytest
from fastapi import Response

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db
from melorin.core.errors import AppError
from melorin.core.security import _totp, totp_new_secret
from melorin.modules.identity import router, service
from melorin.modules.identity.models import Identity, IdentityLinkReview, RefreshToken, User
from melorin.modules.identity.schemas import GoogleLogin
from melorin.modules.system.models import AuditEvent, SecurityEvent

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent
TABLES = [User.__table__, Identity.__table__, RefreshToken.__table__, IdentityLinkReview.__table__, AuditEvent.__table__, SecurityEvent.__table__]
REQ = types.SimpleNamespace(headers={"user-agent": "pytest"})


@pytest.fixture
async def world(tmp_path, monkeypatch):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/google.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=TABLES))
    secret = totp_new_secret()
    monkeypatch.setattr(router, "decrypt", lambda v: v)  # keep the TOTP secret readable without a Fernet key
    async with db.session_factory()() as s:
        admin = User(display_name="Admin", email="admin@example.com", is_super_admin=True, totp_enabled=True, totp_secret_enc=secret)
        plain_admin = User(display_name="NoTotp", email="nt@example.com", is_super_admin=True)
        cust = User(display_name="Cust", email="c@example.com")
        s.add_all([admin, plain_admin, cust])
        await s.flush()
        for u, sub in ((admin, "g-admin"), (plain_admin, "g-nt"), (cust, "g-cust")):
            s.add(Identity(user_id=u.id, provider="google", subject=sub, data={}))
        await s.commit()

        async def fake_verify(_token):
            return {"sub": fake_verify.sub, "email": "x@example.com", "email_verified": "true"}

        monkeypatch.setattr(service, "verify_google_token", fake_verify)
        yield types.SimpleNamespace(s=s, secret=secret, verify=fake_verify, admin=admin)
    await db.engine().dispose()


async def _login(w, sub, code=None):
    w.verify.sub = sub
    resp = Response()
    pair = await router.google_login(GoogleLogin(id_token="t", totp_code=code), w.s, REQ, resp)
    return pair, resp


async def test_customer_google_login_sets_refresh_cookie(world):
    pair, resp = await _login(world, "g-cust")
    assert pair.is_admin is False
    assert "melorin_refresh" in resp.headers.get("set-cookie", "")


async def test_super_admin_cannot_bypass_totp_via_google(world):
    with pytest.raises(AppError) as e:
        await _login(world, "g-admin")
    assert e.value.code == "TOTP_REQUIRED"
    with pytest.raises(AppError) as e:
        await _login(world, "g-admin", "000000")
    assert e.value.code == "TOTP_REQUIRED"


async def test_super_admin_without_totp_enrolled_is_refused(world):
    with pytest.raises(AppError) as e:
        await _login(world, "g-nt")
    assert e.value.code == "ADMIN_2FA_REQUIRED"


async def test_super_admin_with_valid_totp_logs_in_once_replay_rejected(world):
    code = _totp(world.secret, int(time.time()) // 30)
    pair, resp = await _login(world, "g-admin", code)
    assert pair.is_admin is True and "melorin_refresh" in resp.headers.get("set-cookie", "")
    with pytest.raises(AppError) as e:
        await _login(world, "g-admin", code)
    assert e.value.code == "TOTP_REQUIRED"


def test_csp_allows_google_identity_services_on_every_site():
    caddy = (PROJECT / "infra/Caddyfile").read_text()
    policies = [ln for ln in caddy.splitlines() if "Content-Security-Policy" in ln]
    assert len(policies) == 3
    for ln in policies:
        assert "script-src 'self' https://accounts.google.com/gsi/client" in ln
        assert "frame-src https://accounts.google.com/gsi/" in ln
        assert "https://accounts.google.com/gsi/style" in ln
        assert "'unsafe-eval'" not in ln


def test_google_client_id_reaches_both_frontend_builds():
    compose = (PROJECT / "docker-compose.yml").read_text()
    assert compose.count("VITE_GOOGLE_CLIENT_ID: ${MELORIN_GOOGLE_CLIENT_ID:-}") == 2
    for app in ("store-web", "admin-web"):
        assert "ARG VITE_GOOGLE_CLIENT_ID" in (PROJECT / f"apps/{app}/Dockerfile").read_text()
        hook = (PROJECT / f"apps/{app}/src/GoogleSignIn.jsx").read_text()
        assert "latest.current(response.credential)" in hook and "isDismissedMoment" in hook
