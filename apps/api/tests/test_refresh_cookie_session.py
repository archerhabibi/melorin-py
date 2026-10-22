from pathlib import Path

from _source import read_source, read_web_source

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent.parent


def test_refresh_session_uses_httponly_cookie():
    router = read_source(ROOT / "melorin/modules/identity/router.py")
    auth = read_web_source(PROJECT / "apps/admin-web/src/auth.js")
    main = read_web_source(PROJECT / "apps/admin-web/src/main.jsx")
    assert "httponly=True" in router and "REFRESH_COOKIE" in router
    assert "refreshToken" not in auth
    assert 'credentials: "include"' in main


def test_refresh_body_remains_optional_for_compatibility():
    schema = read_source(ROOT / "melorin/modules/identity/schemas.py")
    assert "refresh_token: str | None = None" in schema
