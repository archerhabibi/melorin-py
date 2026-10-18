from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent


def test_refresh_session_uses_httponly_cookie():
    router = read_source(ROOT / "melorin/modules/identity/router.py")
    auth = (PROJECT / "apps/admin-web/src/auth.js").read_text()
    main = (PROJECT / "apps/admin-web/src/main.jsx").read_text()
    assert "httponly=True" in router and "REFRESH_COOKIE" in router
    assert "refreshToken" not in auth
    assert 'credentials: "include"' in main


def test_refresh_body_remains_optional_for_compatibility():
    schema = read_source(ROOT / "melorin/modules/identity/schemas.py")
    assert "refresh_token: str | None = None" in schema
