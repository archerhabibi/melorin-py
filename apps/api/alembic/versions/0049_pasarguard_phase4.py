"""PasarGuard roadmap Phase 4 (PG-07 console, PG-11 bulk operations, PG-12 store governance, PG-13 subscription check).

* ``bulk_operations`` / ``bulk_operation_items``  preview -> confirm -> chunked, resumable run with a per-account ledger
* ``panel_admins``   governance: requested traffic cap, last reported status / usage / user count
* ``stores.suspend_policy``  what a store suspension does to its accounts on the panel (``none`` keeps today's behaviour)
* ``panels.subscription_check`` / ``subscription_checked_at``  last result of the subscription test

Additive and defaulted: every existing row keeps today's behaviour until an admin opts in.
"""

import sqlalchemy as sa
from alembic import op

revision = "0049_pasarguard_phase4"
down_revision = "0048_pasarguard_phase3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bulk_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("panel_id", sa.Uuid(), sa.ForeignKey("panels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("selection", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(300), nullable=True),
        sa.Column("origin", sa.String(20), nullable=False, server_default="admin"),
        sa.Column("status", sa.String(12), nullable=False, server_default="previewed"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bulk_operations_panel_id", "bulk_operations", ["panel_id"])
    op.create_index("ix_bulk_operations_store_id", "bulk_operations", ["store_id"])
    op.create_index("ix_bulk_operations_status", "bulk_operations", ["status"])
    op.create_index("ix_bulk_operations_status_created", "bulk_operations", ["status", "created_at"])
    op.create_table(
        "bulk_operation_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("bulk_operations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vpn_account_id", sa.Uuid(), sa.ForeignKey("vpn_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("panel_ref", sa.String(200), nullable=True),
        sa.Column("target", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("operation_id", "vpn_account_id", name="uq_bulk_items_operation_account"),
    )
    op.create_index("ix_bulk_operation_items_operation_id", "bulk_operation_items", ["operation_id"])
    op.create_index("ix_bulk_operation_items_vpn_account_id", "bulk_operation_items", ["vpn_account_id"])
    op.create_index("ix_bulk_operation_items_status", "bulk_operation_items", ["status"])

    op.add_column("panel_admins", sa.Column("data_limit_bytes", sa.BigInteger(), nullable=True))
    op.add_column("panel_admins", sa.Column("remote_status", sa.String(12), nullable=True))
    op.add_column("panel_admins", sa.Column("used_traffic_bytes", sa.BigInteger(), nullable=True))
    op.add_column("panel_admins", sa.Column("total_users", sa.Integer(), nullable=True))
    op.add_column("panel_admins", sa.Column("usage_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("panel_admins", sa.Column("governance_error", sa.String(300), nullable=True))
    op.add_column("stores", sa.Column("suspend_policy", sa.String(20), nullable=False, server_default="none"))
    op.add_column("panels", sa.Column("subscription_check", sa.JSON(), nullable=True))
    op.add_column("panels", sa.Column("subscription_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("panels", "subscription_checked_at")
    op.drop_column("panels", "subscription_check")
    op.drop_column("stores", "suspend_policy")
    for col in ("governance_error", "usage_checked_at", "total_users", "used_traffic_bytes", "remote_status", "data_limit_bytes"):
        op.drop_column("panel_admins", col)
    op.drop_table("bulk_operation_items")
    op.drop_table("bulk_operations")
