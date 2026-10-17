from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_new_products_are_published_to_main_store():
    source = (ROOT / "melorin/modules/admin/router.py").read_text()
    assert "StoreProduct(" in source
    assert 'Store.kind == "main"' in source
    assert "is_enabled=True" in source and "is_listed=True" in source


def test_existing_products_are_backfilled():
    migration = (ROOT / "alembic/versions/0011_backfill_main_products.py").read_text()
    assert "INSERT INTO store_products" in migration
    assert "NOT EXISTS" in migration
    assert "0010_sales_baskets" in migration


def test_panel_group_is_reachable_from_public_catalog():
    source = (ROOT / "melorin/modules/catalog/router.py").read_text()
    assert '"/stores/{store_id}/panel-groups"' in source
    assert "allocation.sellable_bundles" in source  # the list itself comes from the core


def test_baskets_are_renamed_to_panel_groups_everywhere():
    migration = (ROOT / "alembic/versions/0012_baskets_to_panel_groups.py").read_text()
    assert 'down_revision = "0011_backfill_main_products"' in migration
    assert len("0012_baskets_to_panel_groups") <= 32  # alembic_version.version_num is VARCHAR(32)
    for old, new in (("sales_baskets", "panel_groups"), ("sales_basket_panels", "panel_group_members"), ("store_sales_baskets", "store_panel_groups")):
        assert f'"{old}": "{new}"' in migration
    live = [p for p in (ROOT / "melorin").rglob("*.py")]
    assert live and not [p for p in live if "basket" in p.read_text().lower()]
    assert not (ROOT / "melorin/modules/vpn/baskets.py").exists()
