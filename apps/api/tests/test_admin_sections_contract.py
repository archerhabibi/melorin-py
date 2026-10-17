from pathlib import Path


def test_admin_sections_have_live_data_contracts():
    ui = Path(__file__).parents[3].joinpath("apps", "admin-web", "src", "AdminSections.jsx").read_text()
    api = Path(__file__).parents[1].joinpath("melorin", "modules", "admin", "router.py").read_text()
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
