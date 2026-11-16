from pathlib import Path

from _source import read_source, web_file

SRC = Path(__file__).resolve().parents[3] / "admin-web" / "src"


def test_admin_web_never_uses_browser_storage_or_remote_fonts():
    for path in SRC.glob("*.js*"):
        text = path.read_text()
        assert "localStorage" not in text, path.name
        assert "sessionStorage" not in text, path.name
        assert "fonts.googleapis.com" not in text, path.name


def test_admin_dashboard_has_no_hardcoded_date_and_uses_shared_client():
    # App.tsx was split (r5): shell, session and dashboard modules together
    app = "".join(web_file(SRC / n).read_text() for n in ("App.tsx", "AdminShell.tsx", "AdminSession.tsx", "Dashboard.tsx"))
    assert "۱۴۰۵" not in app
    assert "downloadFile" in app and "todayLabel()" in app  # views reach authFetch only through api.ts helpers


def test_email_code_login_links_existing_user_instead_of_duplicating():
    service = read_source(SRC.parents[1] / "api/melorin/modules/identity/service.py")
    assert "select(User).where(User.email == email)" in service
    cli = read_source(SRC.parents[1] / "api/melorin/cli.py")
    assert 'Identity.provider == "email"' in cli
