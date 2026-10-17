"""0022 - Rename panel groups to sales bundles.

Tables:  ``panel_groups`` -> ``bundles``, ``panel_group_members`` -> ``bundle_members``, ``store_panel_groups`` -> ``store_bundles``.
Columns: ``panel_group_id`` -> ``bundle_id`` (bundle_members, store_bundles, bundle_products, store_bundle_prices, orders) and
         ``products.default_panel_group_id`` -> ``default_bundle_id``.
Indexes, unique and foreign-key constraints whose names embed the old words are renamed too (PostgreSQL). Data is preserved
and the downgrade restores the old names. Audit history is left untouched.
"""
import sqlalchemy as sa
from alembic import op

revision = "0022_panel_group_to_bundle"
down_revision = "0021_pool_to_bundle"
branch_labels = None
depends_on = None

TABLES = {"panel_groups": "bundles", "panel_group_members": "bundle_members", "store_panel_groups": "store_bundles"}
# (table after the rename, old column, new column)
COLUMNS = [
    ("bundle_members", "panel_group_id", "bundle_id"),
    ("store_bundles", "panel_group_id", "bundle_id"),
    ("bundle_products", "panel_group_id", "bundle_id"),
    ("store_bundle_prices", "panel_group_id", "bundle_id"),
    ("orders", "panel_group_id", "bundle_id"),
    ("products", "default_panel_group_id", "default_bundle_id"),
]
# Longest first so "store_panel_groups" is not clobbered by "panel_groups".
NAME_MAP = [
    ("store_panel_groups", "store_bundles"),
    ("panel_group_members", "bundle_members"),
    ("default_panel_group", "default_bundle"),
    ("panel_group_id", "bundle_id"),
    ("panel_groups", "bundles"),
    # explicit name given by 0016; the model's naming convention yields the column-based one
    ("uq_bundle_products_bundle_product", "uq_bundle_products_bundle_id_product_id"),
]
TOUCHED = ["bundles", "bundle_members", "store_bundles", "bundle_products", "store_bundle_prices", "orders", "products"]


def _rename(name: str, mapping) -> str:
    for old, new in mapping:
        name = name.replace(old, new)
    return name


def _rename_named_objects(mapping, tables) -> None:
    """Rename indexes / primary-key / unique / foreign-key constraints whose names embed the old words (PostgreSQL)."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    insp = sa.inspect(bind)
    for table in tables:
        if not insp.has_table(table):
            continue
        for ix in insp.get_indexes(table):
            new = _rename(ix["name"], mapping)
            if new != ix["name"]:
                op.execute(f'ALTER INDEX IF EXISTS "{ix["name"]}" RENAME TO "{new}"')
        pk = insp.get_pk_constraint(table).get("name")
        if pk and _rename(pk, mapping) != pk:
            op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{pk}" TO "{_rename(pk, mapping)}"')
        for uq in insp.get_unique_constraints(table):
            new = _rename(uq["name"], mapping)
            if new != uq["name"]:
                op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{uq["name"]}" TO "{new}"')
        for fk in insp.get_foreign_keys(table):
            if fk.get("name"):
                new = _rename(fk["name"], mapping)
                if new != fk["name"]:
                    op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{fk["name"]}" TO "{new}"')


def _sqlite_indexes(mapping, tables) -> None:
    """SQLite cannot rename an index: drop and recreate (PostgreSQL is handled by ALTER INDEX above)."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    insp = sa.inspect(bind)
    for table in tables:
        if not insp.has_table(table):
            continue
        for ix in insp.get_indexes(table):
            new = _rename(ix["name"], mapping)
            if new != ix["name"]:
                op.drop_index(ix["name"], table_name=table)
                op.create_index(new, table, ix["column_names"], unique=bool(ix.get("unique")))


def upgrade():
    for old, new in TABLES.items():
        op.rename_table(old, new)
    for table, old, new in COLUMNS:
        op.alter_column(table, old, new_column_name=new)
    _rename_named_objects(NAME_MAP, TOUCHED)
    _sqlite_indexes(NAME_MAP, TOUCHED)


def downgrade():
    # the explicit unique-constraint name first, so the generic "bundle_id" rule does not rewrite it
    inverse = [("uq_bundle_products_bundle_id_product_id", "uq_bundle_products_bundle_product")]
    inverse += [(new, old) for old, new in NAME_MAP if not old.startswith("uq_")]
    # PostgreSQL index names embed the new words now; rename them back before the tables/columns move.
    _rename_named_objects(inverse, TOUCHED)
    _sqlite_indexes(inverse, TOUCHED)
    for table, old, new in COLUMNS:
        op.alter_column(table, new, new_column_name=old)
    for old, new in TABLES.items():
        op.rename_table(new, old)
