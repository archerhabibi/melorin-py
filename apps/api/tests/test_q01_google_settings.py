"""Google Sign-In is configured at runtime from the admin panel (Settings > Google login)."""

import types
from pathlib import Path

import pytest
from fastapi import Response

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import config as config_mod
from melorin.core import db, integrations, settings_store
from melorin.core.errors import AppError
from melorin.modules.admin import integrations as admin_integrations
from melorin.modules.identity import router, service
from melorin.modules.identity.models import Identity, IdentityLinkReview, RefreshToken, User
from melorin.modules.identity.schemas import GoogleLogin
from melorin.modules.stores.models import Store
from melorin.modules.system.models import AuditEvent, SecurityEvent, SystemSetting

PROJECT = Path(__file__).resolve().parents[3]
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
GOOD_ID = "123456789012-abc123def456.apps.googleusercontent.com"
REQ = types.SimpleNamespace(
    headers={"user-agent": "pytest", "host": "localhost"},
    client=types.SimpleNamespace(host="203.0.113.9"),
    cookies={router.GOOGLE_NONCE_COOKIE: "n1"},
)


@pytest.fixture
async def session(tmp_path, monkeypatch):
    monkeypatch.delenv("MELORIN_GOOGLE_CLIENT_ID", raising=False)
    config_mod.get_settings.cache_clear()
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/g.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=TABLES))
    async with db.session_factory()() as s:
        s.add(Store(kind="main", name="Main", slug="main"))
        await s.flush()
        yield s
    await db.engine().dispose()
    config_mod.get_settings.cache_clear()


def test_client_id_format():
    assert integrations.GOOGLE_CLIENT_ID_RE.match(GOOD_ID)
    for bad in ("", "abc", "123.apps.googleusercontent.com", "https://x.apps.googleusercontent.com", GOOD_ID + "/", " " + GOOD_ID):
        assert not integrations.GOOGLE_CLIENT_ID_RE.match(bad)


async def test_default_is_off_and_public_view_hides_the_id_when_disabled(session):
    cfg = await integrations.get_google(session)
    assert cfg["source"] == "none" and not integrations.google_ready(cfg)
    assert integrations.public_google({**cfg, "client_id": GOOD_ID}) == {
        "enabled": False,
        "client_id": "",
        "admin_login": True,
        "store_login": True,
    }


async def test_env_value_keeps_working_until_the_panel_saves(session, monkeypatch):
    monkeypatch.setenv("MELORIN_GOOGLE_CLIENT_ID", GOOD_ID)
    config_mod.get_settings.cache_clear()
    cfg = await integrations.get_google(session)
    assert cfg["source"] == "env" and integrations.google_ready(cfg) and cfg["client_id"] == GOOD_ID
    # once the admin saves in the panel, the panel wins (including turning Google off)
    await settings_store.set_value(session, integrations.GOOGLE_KEY, {"enabled": False, "client_id": GOOD_ID})
    cfg = await integrations.get_google(session)
    assert cfg["source"] == "panel" and not integrations.google_ready(cfg)


async def test_admin_update_validates_and_stores(session):
    admin = types.SimpleNamespace(id=None)
    with pytest.raises(AppError) as e:
        await admin_integrations.update_google(admin_integrations.GoogleIn(enabled=True, client_id=""), admin, session)
    assert e.value.code == "GOOGLE_CONFIG_INCOMPLETE"
    with pytest.raises(AppError) as e:
        await admin_integrations.update_google(admin_integrations.GoogleIn(enabled=False, client_id="nope"), admin, session)
    assert e.value.code == "GOOGLE_CLIENT_ID_INVALID"
    with pytest.raises(AppError) as e:
        await admin_integrations.update_google(
            admin_integrations.GoogleIn(enabled=True, client_id=GOOD_ID, admin_login=False, store_login=False), admin, session
        )
    assert e.value.code == "GOOGLE_NO_SURFACE"
    out = await admin_integrations.update_google(
        admin_integrations.GoogleIn(enabled=True, client_id=f"  {GOOD_ID} ", store_login=False), admin, session
    )
    assert out["client_id"] == GOOD_ID and out["enabled"] and out["admin_login"] and not out["store_login"] and out["source"] == "panel"
    stored = await integrations.get_google(session)
    assert stored["client_id"] == GOOD_ID and stored["source"] == "panel"


async def test_public_config_endpoint(session):
    await settings_store.set_value(
        session, integrations.GOOGLE_KEY, {"enabled": True, "client_id": GOOD_ID, "admin_login": True, "store_login": False}
    )
    await session.commit()
    resp = Response()
    out = await router.google_config(session, resp)
    assert out == {"enabled": True, "client_id": GOOD_ID, "admin_login": True, "store_login": False}
    assert resp.headers["cache-control"] == "no-store"


async def test_login_refused_when_disabled(session):
    with pytest.raises(AppError) as e:
        await router.google_login(GoogleLogin(id_token="t"), session, REQ, Response())
    assert e.value.code == "GOOGLE_DISABLED"


async def _login_as(session, monkeypatch, *, admin: bool, admin_login: bool, store_login: bool):
    await settings_store.set_value(
        session, integrations.GOOGLE_KEY, {"enabled": True, "client_id": GOOD_ID, "admin_login": admin_login, "store_login": store_login}
    )
    u = User(display_name="U", email="u@example.com", is_super_admin=admin)
    session.add(u)
    await session.flush()
    session.add(Identity(user_id=u.id, provider="google", subject="sub-1", data={}))
    await session.commit()

    async def fake_verify(_t, _c):
        return {"sub": "sub-1", "email": "u@example.com", "email_verified": "true", "nonce": "n1"}

    monkeypatch.setattr(service, "verify_google_token", fake_verify)
    return await router.google_login(GoogleLogin(id_token="t"), session, REQ, Response())


async def test_store_login_switch_blocks_customers(session, monkeypatch):
    with pytest.raises(AppError) as e:
        await _login_as(session, monkeypatch, admin=False, admin_login=True, store_login=False)
    assert e.value.code == "GOOGLE_STORE_DISABLED"


async def test_admin_login_switch_blocks_admins_before_totp(session, monkeypatch):
    with pytest.raises(AppError) as e:
        await _login_as(session, monkeypatch, admin=True, admin_login=False, store_login=True)
    assert e.value.code == "GOOGLE_ADMIN_DISABLED"


async def test_store_login_switch_allows_customers(session, monkeypatch):
    pair = await _login_as(session, monkeypatch, admin=False, admin_login=False, store_login=True)
    assert pair.is_admin is False


def test_integration_keys_stay_out_of_generic_settings():
    assert integrations.is_integration_key(integrations.GOOGLE_KEY)


def test_google_ui_is_wired_into_settings_and_login_pages():
    extra = (PROJECT / "apps/admin-web/src/AdminExtra.jsx").read_text()
    assert "<GoogleLoginSettings" in extra
    ui = (PROJECT / "apps/admin-web/src/GoogleLoginSettings.jsx").read_text()
    assert "/api/v1/admin/integrations/google" in ui and "apps.googleusercontent.com" in ui
    for app in ("admin-web", "store-web"):
        hook = (PROJECT / f"apps/{app}/src/GoogleSignIn.jsx").read_text()
        assert "/api/v1/auth/google/config" in hook and "useGoogleConfig" in hook
