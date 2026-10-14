from pathlib import Path

SRC = Path(__file__).parents[3].joinpath("apps", "admin-web", "src")
ALLOCATION = Path(__file__).parents[1].joinpath("melorin", "modules", "vpn", "allocation.py").read_text()
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
    infra = _ui("infra.jsx")
    assert "/api/v1/admin/products" in infra and "/api/v1/admin/panels" in infra and "useInfra" in ui


def test_servers_are_their_own_infrastructure_page_not_a_tab_of_panels():
    panels = _ui("PanelsView.jsx")
    assert "ServersView" not in panels and 'role="tablist"' not in panels
    extra = _ui("AdminExtra.jsx")
    assert '"سرورها": ServersView' in extra and '"پنل‌ها": PanelsView' in extra
    app = _ui("App.jsx")
    assert "['سرورها', ServerCog, 'servers']" in app
    # servers sit inside the infrastructure group, between panels and panel groups
    infra_group = app[app.index("['زیرساخت'"):app.index("['سیستم'")]
    assert infra_group.index("'panels'") < infra_group.index("'servers'") < infra_group.index("'panel-groups'") < infra_group.index("'products'")


def test_infra_screens_share_one_dependency_model():
    infra = _ui("infra.jsx")
    for endpoint in ("/api/v1/admin/panels", "/api/v1/admin/servers", "/api/v1/admin/panel-groups", "/api/v1/admin/products"):
        assert endpoint in infra
    for page in ("PanelsView.jsx", "ServersView.jsx", "PanelGroupsView.jsx", "ProductsView.jsx"):
        ui = _ui(page)
        assert "useInfra" in ui and "InfraChain" in ui, page
    # an unknown panel health blocks allocation in the core, so the UI must treat it as not ready
    assert 'panel.health_status == "healthy"' in ALLOCATION and 'h === "unknown"' in infra


def test_server_edit_never_resends_unchanged_fields():
    form = _ui("ServerForm.jsx")
    assert 'method = "PATCH"' in form and "JSON.stringify(v) !== JSON.stringify(was[k])" in form
