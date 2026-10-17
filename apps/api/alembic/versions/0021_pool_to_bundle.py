"""0021 - Rename sales pools to sales bundles: ``pool_products`` -> ``bundle_products``, ``store_pool_prices`` -> ``store_bundle_prices``.

Tables, indexes, unique and foreign-key constraints are renamed; data is preserved and the downgrade restores the old names.
Audit history is left untouched (old rows keep their original action names).
"""
import sqlalchemy as sa
from alembic import op

revision = "0021_pool_to_bundle"
down_revision = "0020_store_pool_prices"
branch_labels = None
depends_on = None

TABLES = {"pool_products": "bundle_products", "store_pool_prices": "store_bundle_prices"}
NAME_MAP = [("pool", "bundle")]


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


def upgrade():
    for old, new in TABLES.items():
        op.rename_table(old, new)
    _rename_named_objects(NAME_MAP, list(TABLES.values()))
    _sqlite_indexes(upgrade=True)


def downgrade():
    for old, new in TABLES.items():
        op.rename_table(new, old)
    _rename_named_objects([("bundle", "pool")], list(TABLES.keys()))
    _sqlite_indexes(upgrade=False)


def _sqlite_indexes(upgrade: bool) -> None:
    """SQLite cannot rename an index: drop and recreate (PostgreSQL already handled by ALTER INDEX above)."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    old, new = ("pool", "bundle") if upgrade else ("bundle", "pool")
    insp = sa.inspect(bind)
    tables = TABLES.values() if upgrade else TABLES.keys()
    for table in tables:
        for ix in insp.get_indexes(table):
            if old in ix["name"]:
                op.drop_index(ix["name"], table_name=table)
                op.create_index(ix["name"].replace(old, new), table, ix["column_names"], unique=bool(ix.get("unique")))
