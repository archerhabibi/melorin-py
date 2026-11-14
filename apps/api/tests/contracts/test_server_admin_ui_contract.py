from pathlib import Path

from _source import read_source, read_web_source

SRC = Path(__file__).parents[4].joinpath("apps", "admin-web", "src")
ALLOCATION = read_source(Path(__file__).parents[2].joinpath("melorin", "modules", "catalog", "allocation.py"))
ROUTER = read_source(Path(__file__).parents[2].joinpath("melorin", "modules", "admin", "router.py"))


def _ui(name: str) -> str:
    return read_web_source(SRC.joinpath(name))


def test_servers_ui_uses_only_endpoints_that_exist():
    ui = _ui("PanelsView.tsx") + _ui("ServerForm.tsx")
    for route, decorator in (
        ("/api/v1/admin/servers", '@router.get("/servers"'),
        ("/api/v1/admin/servers", '@router.post("/servers"'),
        ("/api/v1/admin/servers/${server.id}", '@router.patch("/servers/{server_id}"'),
        ("/api/v1/admin/servers/${s.id}/state", '@router.post("/servers/{server_id}/state"'),
    ):
        assert route in ui and decorator in ROUTER
    infra = _ui("infra.tsx")
    assert "/api/v1/admin/products" in infra and "/api/v1/admin/panels" in infra and "useInfra" in ui


def test_servers_live_inside_their_panel_screen():
    """A server is only a capacity slot of one panel: no separate Servers screen, one merged page."""
    assert not SRC.joinpath("ServersView.tsx").exists()
    panels = _ui("PanelsView.tsx")
    assert "ServerForm" in panels and "ServerImport" in panels
    extra = _ui("AdminExtra.tsx")
    assert '"پنل‌ها و سرورها": PanelsView' in extra and "ServersView" not in extra
    app = _ui("adminNav.ts")  # menu groups live in adminNav.ts since the App.tsx split
    assert '["پنل‌ها و سرورها", PanelTop, "panels"]' in app and '"servers"' not in app
    # menu regroup: the panel screen leads the infrastructure group; bundles and products are catalog entries next to marketing
    infra_group = app[app.index('"زیرساخت"') : app.index('"سیستم"')]
    assert '"panels"' in infra_group and '"bundles"' not in infra_group
    catalog_group = app[app.index('"کاتالوگ و بازاریابی"') : app.index('"ارتباطات"')]
    assert catalog_group.index('"bundles"') < catalog_group.index('"products"')
    # old bookmarks (#/servers?panel=<id>) still land on the merged screen
    assert "legacyHash" in app and "legacyHash" in _ui("infra.tsx")


def test_infra_screens_share_one_dependency_model():
    infra = _ui("infra.tsx")
    for endpoint in ("/api/v1/admin/panels", "/api/v1/admin/servers", "/api/v1/admin/bundles", "/api/v1/admin/products"):
        assert endpoint in infra
    for page in ("PanelsView.tsx", "BundlesView.tsx", "ProductsView.tsx"):
        ui = _ui(page)
        assert "useInfra" in ui and "InfraChain" in ui, page
    # an unknown panel health blocks allocation in the core, so the UI must treat it as not ready; ``degraded`` (a node fails, the
    # panel still serves) sells, so the UI must not block it (PG-01)
    assert "panel.health_status in SELLABLE_STATES" in ALLOCATION and 'h === "unknown"' in infra and '"degraded"' in infra


def test_server_edit_never_resends_unchanged_fields():
    form = _ui("ServerForm.tsx")
    assert 'method = "PATCH"' in form and "JSON.stringify(v) !== JSON.stringify(was[k])" in form


def test_group_membership_is_saved_with_the_field_the_api_reads():
    """Regression: the panel form used to PATCH {panels: [...]}, which the API ignores (field is panel_ids)."""
    schemas = read_source(Path(__file__).parents[2].joinpath("melorin", "modules", "admin", "schemas.py"))
    update = schemas[schemas.index("class UpdateBundle") : schemas.index("class BundleMemberInput")]
    assert "panel_ids" in update
    infra = _ui("infra.tsx")
    assert "JSON.stringify({panel_ids: panelIds})" in infra
    assert "JSON.stringify({ panels:" not in _ui("PanelsView.tsx")


def test_bundle_screen_manages_packages_through_bundle_endpoints():
    """The bundle screen edits packages (and per-bundle prices) via /bundles/{id}/products, never via the product PATCH."""
    groups = _ui("BundlesView.tsx") + _ui("bundles/BundleDrawer.tsx") + _ui("bundles/BundleParts.tsx")  # split by T31
    assert "/products/" in groups and "kind_label" in groups and "member_labels" in groups
    assert "default_bundle_id" not in groups
    assert "PRODUCT_DEFAULT_BUNDLE" in ROUTER and "/bundles/{bundle_id}/products" in ROUTER
