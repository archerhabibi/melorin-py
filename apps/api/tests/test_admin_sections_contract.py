from pathlib import Path

from _source import read_source


def test_admin_sections_have_live_data_contracts():
    ui = Path(__file__).parents[3].joinpath("apps", "admin-web", "src", "AdminSections.jsx").read_text()
    api = read_source(Path(__file__).parents[1].joinpath("melorin", "modules", "admin", "router.py"))
    for route in (
        "/api/v1/admin/payments",
        "/api/v1/admin/orders",
        "/api/v1/admin/vpn-accounts",
        "/api/v1/admin/users",
        "/api/v1/admin/tickets",
        "/api/v1/admin/stores",
    ):
        assert route in ui
    assert "async def vpn_accounts" in api
