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


def downgrade() -> None:
    op.drop_constraint("uq_payments_user_store_idempotency_key", "payments", type_="unique")
    op.create_unique_constraint("uq_payments_user_id_idempotency_key", "payments", ["user_id", "idempotency_key"])
    op.drop_constraint("uq_orders_user_store_idempotency_key", "orders", type_="unique")
    op.create_unique_constraint("uq_orders_user_id_idempotency_key", "orders", ["user_id", "idempotency_key"])
