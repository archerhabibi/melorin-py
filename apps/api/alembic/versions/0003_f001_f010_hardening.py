"""F001-F010 hardening constraints.

Revision ID: 0003_f001_f010
Revises: 0002_v11
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_f001_f010"
down_revision = "0002_v11"
branch_labels = None
depends_on = None


def _swap_idempotency_constraint(table: str, new_name: str) -> None:
    """Make (user_id, store_id, idempotency_key) unique; works on fresh and legacy schemas."""
    inspector = sa.inspect(op.get_bind())
    wanted = ["idempotency_key", "store_id", "user_id"]
    legacy = ["idempotency_key", "user_id"]
    for uc in inspector.get_unique_constraints(table):
        cols = sorted(uc["column_names"])
        if cols == wanted:
            return  # fresh install: baseline already has it (under any name)
        if cols == legacy:
            op.drop_constraint(uc["name"], table, type_="unique")
    op.create_unique_constraint(new_name, table, ["user_id", "store_id", "idempotency_key"])


def upgrade() -> None:
    _swap_idempotency_constraint("payments", "uq_payments_user_store_idempotency_key")
    _swap_idempotency_constraint("orders", "uq_orders_user_store_idempotency_key")


def _restore_legacy_idempotency_constraint(table: str, legacy_name: str) -> None:
    """Inverse of the swap: drop the (user, store, key) unique constraint under whatever name it has.

    A fresh install gets the three-column constraint from the baseline under a generated name
    (``uq_<table>_user_id_store_id_idempotency_key``), so dropping a hard-coded name fails there.
    """
    inspector = sa.inspect(op.get_bind())
    wanted = ["idempotency_key", "store_id", "user_id"]
    legacy = ["idempotency_key", "user_id"]
    already_legacy = False
    for uc in inspector.get_unique_constraints(table):
        cols = sorted(uc["column_names"])
        if cols == wanted:
            op.drop_constraint(uc["name"], table, type_="unique")
        elif cols == legacy:
            already_legacy = True
    if not already_legacy:
        op.create_unique_constraint(legacy_name, table, ["user_id", "idempotency_key"])


def downgrade() -> None:
    _restore_legacy_idempotency_constraint("payments", "uq_payments_user_id_idempotency_key")
    _restore_legacy_idempotency_constraint("orders", "uq_orders_user_id_idempotency_key")
