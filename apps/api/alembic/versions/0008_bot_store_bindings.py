"""Bot to Store/owner mapping.

Revision ID: 0008_bot_store_bindings
Revises: 0007_admin_security
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_bot_store_bindings"
down_revision = "0007_admin_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This is the sole owner of bot_store_bindings.  The frozen 0001
    # baseline explicitly excludes it, so fresh installs cannot receive
    # duplicate table/index DDL.
    op.create_table(
        "bot_store_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("bot_key", sa.String(120), nullable=False),
        sa.Column("bot_username", sa.String(100), nullable=True),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("bot_kind", sa.String(20), nullable=False, server_default="reseller"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.UniqueConstraint("bot_key"),
        sa.UniqueConstraint("store_id"),
    )
    op.create_index("ix_bot_store_bindings_owner_user_id", "bot_store_bindings", ["owner_user_id"])
    op.create_index("ix_bot_store_bindings_store_id", "bot_store_bindings", ["store_id"])


def downgrade() -> None:
    op.drop_index("ix_bot_store_bindings_store_id", table_name="bot_store_bindings")
    op.drop_index("ix_bot_store_bindings_owner_user_id", table_name="bot_store_bindings")
    op.drop_table("bot_store_bindings")
