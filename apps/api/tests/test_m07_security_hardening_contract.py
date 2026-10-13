from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_product_currency_is_closed_set_and_admin_has_error_boundary():
    schema = (ROOT / "melorin/modules/admin/schemas.py").read_text()
    admin_main = (ROOT.parent / "admin-web/src/main.jsx").read_text()
    assert 'Literal["IRT", "USD", "USDT", "XTR"]' in schema
    assert "AdminErrorBoundary" in admin_main


def test_bootstrap_totp_is_base32_and_not_required_after_bootstrap():
    cli = (ROOT / "melorin/cli.py").read_text()
    config = (ROOT / "melorin/core/config.py").read_text()
    installer = (ROOT.parent.parent / "scripts/install_server.sh").read_text()
    assert "b32decode" in cli
    assert "required merely to restart" in config
    assert "RFC 4648 base32" in installer


def test_admin_access_is_ip_restricted_and_proxy_updates_are_documented():
    deps = (ROOT / "melorin/core/deps.py").read_text()
    config = (ROOT / "melorin/core/config.py").read_text()
    readme = (ROOT.parent.parent / "README.md").read_text()
    assert "ADMIN_IP_NOT_ALLOWED" in deps
    assert "admin_allowed_ips" in config
    assert "docker-compose.external.yml up -d --build" in readme
