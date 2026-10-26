from pathlib import Path

from _source import read_source

SRC = Path(__file__).parents[3].joinpath("apps", "admin-web", "src")

# Each admin screen must read its live data from the matching admin API route.
# Screens live in dedicated view modules (or, for the thin ones, AdminSections.jsx),
# so the contract is "route X is requested by the module that renders screen X".
SCREEN_ROUTES = {
    "/api/v1/admin/payments": ("AdminSections.jsx", "PaymentsView.jsx"),
    "/api/v1/admin/orders": ("OrdersView.jsx",),
    "/api/v1/admin/vpn-accounts": ("VpnAccountsView.jsx",),
    "/api/v1/admin/users": ("UsersView.jsx",),
    "/api/v1/admin/tickets": ("AdminSections.jsx", "TicketsView.jsx"),
    "/api/v1/admin/stores": ("StoresView.jsx",),
}


def test_admin_sections_have_live_data_contracts():
    api = read_source(Path(__file__).parents[1].joinpath("melorin", "modules", "admin", "router.py"))
    for route, modules in SCREEN_ROUTES.items():
        assert any(route in SRC.joinpath(m).read_text() for m in modules), f"{route} is not requested by {modules}"
    assert "async def vpn_accounts" in api


def test_admin_screens_are_routed_to_their_views():
    extra = SRC.joinpath("AdminExtra.jsx").read_text()
    for view in ("OrdersView", "VpnAccountsView", "UsersView", "StoresView", "AuditView"):
        assert f"import('./{view}.jsx')" in extra, f"{view} is not lazy-loaded by AdminExtra.jsx"
        assert f": {view}," in extra, f"{view} is not mapped in extraRoutes"
