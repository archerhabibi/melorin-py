from pathlib import Path

from _source import read_source, read_web_source

SRC = Path(__file__).parents[3].joinpath("apps", "admin-web", "src")
ALLOCATION = read_source(Path(__file__).parents[1].joinpath("melorin", "modules", "catalog", "allocation.py"))
ROUTER = read_source(Path(__file__).parents[1].joinpath("melorin", "modules", "admin", "router.py"))


def _ui(name: str) -> str:
    return read_web_source(SRC.joinpath(name))


def test_servers_ui_uses_only_endpoints_that_exist():
    ui = _ui("PanelsView.jsx") + _ui("ServerForm.jsx")
    for route, decorator in (
        ("/api/v1/admin/servers", '@router.get("/servers"'),
        ("/api/v1/admin/servers", '@router.post("/servers"'),
        ("/api/v1/admin/servers/${server.id}", '@router.patch("/servers/{server_id}"'),
        ("/api/v1/admin/servers/${s.id}/state", '@router.post("/servers/{server_id}/state"'),
    ):
        assert route in ui and decorator in ROUTER
    infra = _ui("infra.jsx")
    assert "/api/v1/admin/products" in infra and "/api/v1/admin/panels" in infra and "useInfra" in ui


def test_servers_live_inside_their_panel_screen():
    """A server is only a capacity slot of one panel: no separate Servers screen, one merged page."""
    assert not SRC.joinpath("ServersView.jsx").exists()
    panels = _ui("PanelsView.jsx")
    assert "ServerForm" in panels and "ServerImport" in panels
    extra = _ui("AdminExtra.jsx")
    assert '"پنل‌ها و سرورها": PanelsView' in extra and "ServersView" not in extra
    app = _ui("App.jsx")
    assert '["پنل‌ها و سرورها", PanelTop, "panels"]' in app and '"servers"' not in app
    infra_group = app[app.index('["زیرساخت"') : app.index('["سیستم"')]
    assert infra_group.index('"panels"') < infra_group.index('"bundles"') < infra_group.index('"products"')
    # old bookmarks (#/servers?panel=<id>) still land on the merged screen
    assert "legacyHash" in app and "legacyHash" in _ui("infra.jsx")


def test_infra_screens_share_one_dependency_model():
    infra = _ui("infra.jsx")
    for endpoint in ("/api/v1/admin/panels", "/api/v1/admin/servers", "/api/v1/admin/bundles", "/api/v1/admin/products"):
        assert endpoint in infra
    for page in ("PanelsView.jsx", "BundlesView.jsx", "ProductsView.jsx"):
        ui = _ui(page)
        assert "useInfra" in ui and "InfraChain" in ui, page
    # an unknown panel health blocks allocation in the core, so the UI must treat it as not ready
    assert 'panel.health_status == "healthy"' in ALLOCATION and 'h === "unknown"' in infra


def test_server_edit_never_resends_unchanged_fields():
    form = _ui("ServerForm.jsx")
    assert 'method = "PATCH"' in form and "JSON.stringify(v) !== JSON.stringify(was[k])" in form


def test_group_membership_is_saved_with_the_field_the_api_reads():
    """Regression: the panel form used to PATCH {panels: [...]}, which the API ignores (field is panel_ids)."""
    schemas = read_source(Path(__file__).parents[1].joinpath("melorin", "modules", "admin", "schemas.py"))
    update = schemas[schemas.index("class UpdateBundle") : schemas.index("class BundleMemberInput")]
    assert "panel_ids" in update
    infra = _ui("infra.jsx")
    assert "JSON.stringify({panel_ids: panelIds})" in infra
    assert "JSON.stringify({ panels:" not in _ui("PanelsView.jsx")


def test_bundle_screen_manages_packages_through_bundle_endpoints():
    """The bundle screen edits packages (and per-bundle prices) via /bundles/{id}/products, never via the product PATCH."""
    groups = _ui("BundlesView.jsx")
    assert "/products/" in groups and "kind_label" in groups and "member_labels" in groups
    assert "default_bundle_id" not in groups
    assert "PRODUCT_DEFAULT_BUNDLE" in ROUTER and "/bundles/{bundle_id}/products" in ROUTER
