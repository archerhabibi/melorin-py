from pathlib import Path

SRC = Path(__file__).parents[3].joinpath("apps", "admin-web", "src")
ROUTER = Path(__file__).parents[1].joinpath("melorin", "modules", "admin", "router.py").read_text()


def _ui(name: str) -> str:
    return SRC.joinpath(name).read_text()


def test_servers_ui_uses_only_endpoints_that_exist():
    ui = _ui("ServersView.jsx") + _ui("ServerForm.jsx")
    for route, decorator in (
        ("/api/v1/admin/servers", '@router.get("/servers"'),
        ("/api/v1/admin/servers", '@router.post("/servers"'),
        ("/api/v1/admin/servers/${server.id}", '@router.patch("/servers/{server_id}"'),
        ("/api/v1/admin/servers/${s.id}/state", '@router.post("/servers/{server_id}/state"'),
    ):
        assert route in ui and decorator in ROUTER
    assert "/api/v1/admin/products" in ui and "/api/v1/admin/panels" in ui


def test_panels_page_hosts_the_servers_tab_and_edit_never_resends_unchanged_fields():
    page = _ui("PanelsView.jsx")
    assert "ServersView" in page and 'role="tablist"' in page
    form = _ui("ServerForm.jsx")
    assert 'method = "PATCH"' in form and "JSON.stringify(v) !== JSON.stringify(was[k])" in form
