"""Google Sign-In: the endpoint must keep the same guarantees as the other login paths (admin 2FA, refresh cookie, CSP, build args)."""

from _source import read_web_source
import time
import types
from pathlib import Path

import pytest
from fastapi import Response

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db, integrations, settings_store
from melorin.core.errors import AppError
from melorin.core.security import _totp, totp_new_secret
from melorin.modules.identity import google as google_signin, router, service
from melorin.modules.identity.routes import sign_in
from melorin.kernel.models.identity import Identity, IdentityLinkReview, RefreshToken, User
from melorin.modules.identity.schemas import GoogleLogin
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import AuditEvent, SecurityEvent, SystemSetting

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent
TABLES = [
    User.__table__,
    Identity.__table__,
    RefreshToken.__table__,
    IdentityLinkReview.__table__,
    AuditEvent.__table__,
    SecurityEvent.__table__,
    SystemSetting.__table__,
    Store.__table__,
]
REQ = types.SimpleNamespace(
    headers={"user-agent": "pytest", "host": "localhost"},
    client=types.SimpleNamespace(host="203.0.113.9"),
    cookies={router.GOOGLE_NONCE_COOKIE: "n1"},
)


@pytest.fixture
async def world(tmp_path, monkeypatch):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/google.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c))
    secret = totp_new_secret()
    monkeypatch.setattr(sign_in, "decrypt", lambda v: v)  # keep the TOTP secret readable without a Fernet key
    async with db.session_factory()() as s:
        s.add(Store(kind="main", name="Main", slug="main"))
        await s.flush()
        admin = User(display_name="Admin", email="admin@example.com", is_super_admin=True, totp_enabled=True, totp_secret_enc=secret)
        plain_admin = User(display_name="NoTotp", email="nt@example.com", is_super_admin=True)
        cust = User(display_name="Cust", email="c@example.com")
        s.add_all([admin, plain_admin, cust])
        await s.flush()
        for u, sub in ((admin, "g-admin"), (plain_admin, "g-nt"), (cust, "g-cust")):
            s.add(Identity(user_id=u.id, provider="google", subject=sub, data={}))
        await settings_store.set_value(
            s,
            integrations.GOOGLE_KEY,
            {"enabled": True, "client_id": "123456-abc.apps.googleusercontent.com", "admin_login": True, "store_login": True},
        )
        await s.commit()

        async def fake_verify(_token, _client_id=None):
            return {"sub": fake_verify.sub, "email": "x@example.com", "email_verified": "true", "nonce": "n1"}

        monkeypatch.setattr(google_signin, "verify_google_token", fake_verify)
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


def test_both_apps_use_googles_official_button_with_one_shared_initialisation():
    store = read_web_source(PROJECT / "apps/store-web/src/GoogleSignIn.jsx")
    admin = read_web_source(PROJECT / "apps/admin-web/src/GoogleSignIn.jsx")
    # the two copies differ only by the surface constant and the header comment
    norm = lambda t: t.replace('"store"', '"X"').replace('"admin"', '"X"').replace("store-web", "APP").replace("admin-web", "APP")  # noqa: E731
    assert norm(store) == norm(admin)
    for src in (store, admin):
        assert "renderButton" in src and "accounts.google.com/gsi/client" in src
        assert src.count("initialize({") == 1  # GIS is initialised once, in one place
        assert "nonce" in src and "/api/v1/auth/google/nonce" in src
        assert "filled_black" in src and "outline" in src  # follows the dark/light theme
        assert "locale" in src and "disableAutoSelect" in src
        assert ".prompt(" not in src  # no hand-made button driving One Tap
    assert 'SURFACE = "store"' in store and 'SURFACE = "admin"' in admin


def test_login_pages_use_the_shared_button_and_no_legacy_hook():
    for path in ("apps/store-web/src/App.jsx", "apps/admin-web/src/AdminAuth.jsx"):
        src = (PROJECT / path).read_text()
        assert "<GoogleSignInButton" in src and "useGoogleSignIn" not in src
    admin = read_web_source(PROJECT / "apps/admin-web/src/AdminAuth.jsx")
    assert "payload?.error?.code" in admin  # API errors are {error: {code}}


def test_popup_flow_keeps_window_opener_via_coop_header():
    caddy = (PROJECT / "infra/Caddyfile").read_text()
    assert caddy.count("Cross-Origin-Opener-Policy same-origin-allow-popups") == 3


# ---- linking Google to the signed-in user (Telegram account <-> Google account) ----
async def test_link_google_attaches_identity_to_current_user(world):
    from melorin.modules.identity.schemas import GoogleLink

    tg_user = User(display_name="TG only")
    world.s.add(tg_user)
    await world.s.flush()
    world.verify.sub = "g-new"
    resp = Response()
    out = await router.attach_google(GoogleLink(id_token="t"), tg_user, world.s, REQ, resp)
    assert out == {"ok": True}
    ident = await service.find_identity(world.s, "google", "g-new")
    assert ident is not None and ident.user_id == tg_user.id
    # signing in with that Google account now opens the same user instead of creating a new one
    user, created = await google_signin.login_with_google(world.s, "t", "n1")
    assert created is False and user.id == tg_user.id


async def _link_conflict_world(world, *, tg_has_records, cust_has_records):
    tg_user = User(display_name="TG only", password_hash="x" if tg_has_records else None)
    world.s.add(tg_user)
    cust = await service.find_identity(world.s, "google", "g-cust")
    owner = await world.s.get(User, cust.user_id)
    owner.password_hash = "x" if cust_has_records else None
    await world.s.flush()
    world.verify.sub = "g-cust"  # belongs to the "Cust" user
    return tg_user, owner


async def test_link_google_owned_by_other_user_is_reported_not_merged(world):
    """Both accounts hold something (credentials/records): never merged automatically, queued for an admin."""
    from melorin.modules.identity.schemas import GoogleLink

    tg_user, owner = await _link_conflict_world(world, tg_has_records=True, cust_has_records=True)
    with pytest.raises(AppError) as exc:
        await router.attach_google(GoogleLink(id_token="t"), tg_user, world.s, REQ, Response())
    assert exc.value.status == 409 and exc.value.code == "IDENTITY_LINK_REVIEW"
    assert (await service.find_identity(world.s, "google", "g-cust")).user_id == owner.id


async def test_link_google_owned_by_an_empty_shell_moves_to_the_signed_in_account_by_itself(world):
    from melorin.modules.identity.schemas import GoogleLink

    tg_user, owner = await _link_conflict_world(world, tg_has_records=True, cust_has_records=False)
    assert (await router.attach_google(GoogleLink(id_token="t"), tg_user, world.s, REQ, Response())) == {"ok": True}
    assert (await service.find_identity(world.s, "google", "g-cust")).user_id == tg_user.id
    assert owner.is_active is False and owner.archived_at is not None


async def test_link_google_from_an_empty_shell_session_folds_it_into_the_real_account(world):
    from melorin.modules.identity.schemas import GoogleLink

    tg_user, owner = await _link_conflict_world(world, tg_has_records=False, cust_has_records=True)
    with pytest.raises(AppError) as exc:
        await router.attach_google(GoogleLink(id_token="t"), tg_user, world.s, REQ, Response())
    assert exc.value.code == "IDENTITY_MERGED"
    assert (await service.find_identity(world.s, "google", "g-cust")).user_id == owner.id
    assert tg_user.is_active is False


async def test_link_google_requires_matching_nonce(world):
    from melorin.modules.identity.schemas import GoogleLink

    tg_user = User(display_name="TG only")
    world.s.add(tg_user)
    await world.s.flush()
    world.verify.sub = "g-x"
    bad = types.SimpleNamespace(
        headers={"host": "localhost"}, client=types.SimpleNamespace(host="203.0.113.9"), cookies={router.GOOGLE_NONCE_COOKIE: "other"}
    )
    with pytest.raises(AppError) as exc:
        await router.attach_google(GoogleLink(id_token="t"), tg_user, world.s, bad, Response())
    assert exc.value.status == 401
