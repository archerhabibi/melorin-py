"""Migration 0022: panel groups become sales bundles (tables, columns, indexes) and the downgrade restores the old names."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[1]


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "alembic/versions" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_0022_follows_0021_and_fits_the_version_column():
    m = _load("m0022", "0022_panel_group_to_bundle.py")
    assert m.down_revision == "0021_pool_to_bundle" and len(m.revision) <= 32


def test_0022_renames_tables_and_columns_keeping_data_and_restores_them_on_downgrade():
    m = _load("m0022", "0022_panel_group_to_bundle.py")
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        for sql in (
            "CREATE TABLE panel_groups (id CHAR(32) PRIMARY KEY, name VARCHAR(120))",
            "CREATE TABLE panel_group_members (id CHAR(32) PRIMARY KEY, panel_group_id CHAR(32))",
            "CREATE TABLE store_panel_groups (id CHAR(32) PRIMARY KEY, panel_group_id CHAR(32))",
            "CREATE TABLE bundle_products (id CHAR(32) PRIMARY KEY, panel_group_id CHAR(32))",
            "CREATE TABLE store_bundle_prices (id CHAR(32) PRIMARY KEY, panel_group_id CHAR(32))",
            "CREATE TABLE orders (id CHAR(32) PRIMARY KEY, panel_group_id CHAR(32))",
            "CREATE TABLE products (id CHAR(32) PRIMARY KEY, default_panel_group_id CHAR(32))",
            "CREATE INDEX ix_bundle_products_panel_group_id ON bundle_products (panel_group_id)",
            "INSERT INTO panel_groups VALUES ('g', 'main')",
            "INSERT INTO orders VALUES ('o', 'g')",
            "INSERT INTO products VALUES ('p', 'g')",
        ):
            conn.exec_driver_sql(sql)
        with Operations.context(MigrationContext.configure(conn)):
            m.upgrade()
        insp = sa.inspect(conn)
        assert {"bundles", "bundle_members", "store_bundles"} <= set(insp.get_table_names())
        assert not {"panel_groups", "panel_group_members", "store_panel_groups"} & set(insp.get_table_names())
        assert conn.exec_driver_sql("SELECT name FROM bundles").fetchall() == [("main",)]
        assert conn.exec_driver_sql("SELECT bundle_id FROM orders").fetchall() == [("g",)]
        assert conn.exec_driver_sql("SELECT default_bundle_id FROM products").fetchall() == [("g",)]
        assert "ix_bundle_products_bundle_id" in {i["name"] for i in insp.get_indexes("bundle_products")}
        with Operations.context(MigrationContext.configure(conn)):
            m.downgrade()
        insp = sa.inspect(conn)
        assert {"panel_groups", "panel_group_members", "store_panel_groups"} <= set(insp.get_table_names())
        assert conn.exec_driver_sql("SELECT panel_group_id FROM orders").fetchall() == [("g",)]
        assert "ix_bundle_products_panel_group_id" in {i["name"] for i in insp.get_indexes("bundle_products")}


def test_no_live_code_mentions_panel_groups_or_pools():
    live = [p for p in (ROOT / "melorin").rglob("*.py")]
    offenders = [p.name for p in live if "panel_group" in p.read_text(encoding="utf-8") or "PanelGroup" in p.read_text(encoding="utf-8")]
    assert not offenders, offenders
