"""Rename sales baskets to panel groups (tables, columns, indexes and constraints). Data is preserved."""
import sqlalchemy as sa
from alembic import op

revision = "0012_baskets_to_panel_groups"
down_revision = "0011_backfill_main_products"
branch_labels = None
depends_on = None

TABLES = {
    "sales_baskets": "panel_groups",
    "sales_basket_panels": "panel_group_members",
    "store_sales_baskets": "store_panel_groups",
}
# (table after rename, old column, new column)
COLUMNS = [
    ("panel_group_members", "basket_id", "panel_group_id"),
    ("store_panel_groups", "basket_id", "panel_group_id"),
    ("orders", "basket_id", "panel_group_id"),
]
# Longest first so "store_sales_baskets" is not clobbered by "sales_baskets".
NAME_MAP = [
    ("store_sales_baskets", "store_panel_groups"),
    ("sales_basket_panels", "panel_group_members"),
    ("sales_baskets", "panel_groups"),
    ("basket_id", "panel_group_id"),
]


def _rename(name: str, mapping) -> str:
    for old, new in mapping:
        name = name.replace(old, new)
    return name


def _rename_named_objects(mapping) -> None:
    """Rename indexes / unique / foreign-key constraints whose names embed the old words (PostgreSQL)."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    insp = sa.inspect(bind)
    for table in set(TABLES.values()) | set(TABLES.keys()) | {"orders"}:
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


# Indexes declared on the models (index=True) that migration 0010 never created; adding them keeps `alembic check` clean.
INDEXES = [
    ("ix_panel_group_members_panel_group_id", "panel_group_members", "panel_group_id"),
    ("ix_panel_group_members_panel_id", "panel_group_members", "panel_id"),
    ("ix_store_panel_groups_panel_group_id", "store_panel_groups", "panel_group_id"),
    ("ix_store_panel_groups_store_id", "store_panel_groups", "store_id"),
]


def upgrade():
    for old, new in TABLES.items():
        op.rename_table(old, new)
    for table, old, new in COLUMNS:
        op.alter_column(table, old, new_column_name=new)
    _rename_named_objects(NAME_MAP)
    for name, table, column in INDEXES:
        op.create_index(name, table, [column], if_not_exists=True)


def downgrade():
    inverse = [(new, old) for old, new in NAME_MAP]
    for name, table, _column in INDEXES:
        op.drop_index(name, table_name=table, if_exists=True)
    for table, old, new in COLUMNS:
        op.alter_column(table, new, new_column_name=old)
    for old, new in TABLES.items():
        op.rename_table(new, old)
    _rename_named_objects(inverse)
