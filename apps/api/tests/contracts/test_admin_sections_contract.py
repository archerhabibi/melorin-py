from pathlib import Path

from _source import read_source

SRC = Path(__file__).parents[4].joinpath("apps", "admin-web", "src")

# Each admin screen must read its live data from the matching admin API route.
# Screens live in dedicated view modules (or, for the thin ones, AdminSections.tsx),
# so the contract is "route X is requested by the module that renders screen X".
SCREEN_ROUTES = {
    "/api/v1/admin/payments": ("AdminSections.tsx", "PaymentsView.tsx"),
    "/api/v1/admin/orders": ("OrdersView.tsx",),
    "/api/v1/admin/vpn-accounts": ("VpnAccountsView.tsx",),
    "/api/v1/admin/users": ("UsersView.tsx",),
    "/api/v1/admin/tickets": ("AdminSections.tsx", "TicketsView.tsx"),
    "/api/v1/admin/stores": ("StoresView.tsx",),
}


def test_admin_sections_have_live_data_contracts():
    api = read_source(Path(__file__).parents[2].joinpath("melorin", "modules", "admin", "router.py"))
    for route, modules in SCREEN_ROUTES.items():
        assert any(route in SRC.joinpath(m).read_text() for m in modules), f"{route} is not requested by {modules}"
    assert "async def vpn_accounts" in api


def test_admin_screens_are_routed_to_their_views():
    extra = SRC.joinpath("AdminExtra.tsx").read_text()
    for view in ("OrdersView", "VpnAccountsView", "UsersView", "StoreHubView", "AuditView"):
        assert f"import('./{view}.tsx')" in extra, f"{view} is not lazy-loaded by AdminExtra.tsx"
        assert f": {view}," in extra, f"{view} is not mapped in extraRoutes"
    # the store hub renders the stores list (and the merged reseller / panel-access / volume screens) as tabs
    hub = SRC.joinpath("StoreHubView.tsx").read_text()
    for view in ("StoresView", "ResellersView", "PanelAdminsView", "StoreGovernanceView"):
        assert f"import('./{view}.tsx')" in hub, f"{view} is not a tab of the store hub"
