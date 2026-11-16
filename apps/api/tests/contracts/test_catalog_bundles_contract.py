from pathlib import Path

from _source import read_source

ROOT = Path(__file__).parents[2]


def test_new_products_are_published_to_main_store():
    source = read_source(ROOT / "melorin/modules/admin/router.py")
    assert "StoreProduct(" in source
    assert 'Store.kind == "main"' in source
    assert "is_enabled=True" in source and "is_listed=True" in source


def test_bundle_is_reachable_from_public_catalog():
    source = read_source(ROOT / "melorin/modules/catalog/router.py")
    assert '"/stores/{store_id}/bundles"' in source
    assert "allocation.sellable_bundles" in source  # the list itself comes from the core
