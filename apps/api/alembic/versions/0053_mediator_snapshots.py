"""R7: panel numbers stop being columns. Orphan, panel-admin and destination readings become dated snapshots.

Melorin is a mediator: used traffic, status and user counts belong to the panel. What an admin list still shows of them lives in a
JSON snapshot whose age is an existing timestamp (``last_seen_at``, ``usage_checked_at``, ``capacity_checked_at``). Nothing decides
from them. Melorin has not been released, so the old values are not carried over (the next reconcile / governance run refills them).
"""

import sqlalchemy as sa
from alembic import op

revision = "0053_mediator_snapshots"
down_revision = "0052_capacity_source_panel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("panel_orphans") as batch:
        batch.add_column(sa.Column("snapshot", sa.JSON(), nullable=True))
        for col in ("remote_status", "expire_at", "traffic_limit_bytes", "traffic_used_bytes"):
            batch.drop_column(col)
    with op.batch_alter_table("panel_admins") as batch:
        batch.add_column(sa.Column("usage_snapshot", sa.JSON(), nullable=True))
        for col in ("remote_status", "used_traffic_bytes", "total_users"):
            batch.drop_column(col)
    with op.batch_alter_table("servers") as batch:
        batch.drop_column("panel_total_users")


def downgrade() -> None:
    with op.batch_alter_table("servers") as batch:
        batch.add_column(sa.Column("panel_total_users", sa.Integer(), nullable=True))
    with op.batch_alter_table("panel_admins") as batch:
        batch.add_column(sa.Column("remote_status", sa.String(12), nullable=True))
        batch.add_column(sa.Column("used_traffic_bytes", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("total_users", sa.Integer(), nullable=True))
        batch.drop_column("usage_snapshot")
    with op.batch_alter_table("panel_orphans") as batch:
        batch.add_column(sa.Column("remote_status", sa.String(20), nullable=True))
        batch.add_column(sa.Column("expire_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("traffic_limit_bytes", sa.BigInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("traffic_used_bytes", sa.BigInteger(), nullable=False, server_default="0"))
        batch.drop_column("snapshot")
