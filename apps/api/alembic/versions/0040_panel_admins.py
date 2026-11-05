"""One PasarGuard admin (Operator) per store and panel, plus reseller "Profile & contact" change requests.

* ``panel_admins``                  (panel_id, store_id) unique; username, encrypted password, remote id, sync state, optional profile
* ``panel_admin_change_requests``   a reseller's request to change the profile; the admin applies or rejects it

Additive only: nothing existing is touched; rows are created by the worker's ``panel_admin_sync_job``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0040_panel_admins"
down_revision = "0039_target_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "panel_admins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("panel_id", sa.Uuid(), sa.ForeignKey("panels.id"), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("username", sa.String(34), nullable=False),
        sa.Column("password_enc", sa.Text(), nullable=True),
        sa.Column("remote_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("profile", sa.JSON(), nullable=True),
        sa.Column("profile_synced", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("panel_id", "store_id", name="uq_panel_admins_panel_store"),
    )
    op.create_index("ix_panel_admins_panel_id", "panel_admins", ["panel_id"])
    op.create_index("ix_panel_admins_store_id", "panel_admins", ["store_id"])
    op.create_index("ix_panel_admins_status", "panel_admins", ["status"])
    op.create_table(
        "panel_admin_change_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=True),
    )
    op.create_index("ix_panel_admin_change_requests_store_id", "panel_admin_change_requests", ["store_id"])
    op.create_index("ix_panel_admin_change_requests_status", "panel_admin_change_requests", ["status"])


def downgrade() -> None:
    op.drop_table("panel_admin_change_requests")
    op.drop_table("panel_admins")
