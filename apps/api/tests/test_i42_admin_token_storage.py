from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "admin-web" / "src"


def test_admin_web_never_uses_browser_storage_or_remote_fonts():
    for path in SRC.glob("*.js*"):
        text = path.read_text()
        assert "localStorage" not in text, path.name
        assert "sessionStorage" not in text, path.name
        assert "fonts.googleapis.com" not in text, path.name


def test_admin_dashboard_has_no_hardcoded_date_and_uses_shared_client():
    app = (SRC / "App.jsx").read_text()
    assert "۱۴۰۵" not in app
    assert "authFetch" in app and "todayLabel()" in app


def test_email_code_login_links_existing_user_instead_of_duplicating():
    service = (SRC.parents[1] / "api/melorin/modules/identity/service.py").read_text()
    assert "select(User).where(User.email == email)" in service
    cli = (SRC.parents[1] / "api/melorin/cli.py").read_text()
    assert 'Identity.provider == "email"' in cli
