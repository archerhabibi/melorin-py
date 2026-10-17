"""Reseller bot runtime state on stores.

The reseller runner now takes its bots from Core (``stores.bot_token_enc``) instead of environment variables and
reports its connection state back, so the admin panel can show and control each reseller bot.
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_reseller_bot_runtime"
down_revision = "0024_product_reseller_switch"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stores", sa.Column("bot_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("stores", sa.Column("bot_status", sa.String(20), nullable=True))
    op.add_column("stores", sa.Column("bot_status_detail", sa.String(300), nullable=True))
    op.add_column("stores", sa.Column("bot_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    for col in ("bot_seen_at", "bot_status_detail", "bot_status", "bot_enabled"):
        op.drop_column("stores", col)
