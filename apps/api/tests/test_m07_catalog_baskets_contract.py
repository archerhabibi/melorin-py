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


def test_sales_basket_is_reachable_from_public_catalog():
    source = (ROOT / "melorin/modules/catalog/router.py").read_text()
    assert '"/stores/{store_id}/sales-baskets"' in source
    assert "SalesBasket" in source
