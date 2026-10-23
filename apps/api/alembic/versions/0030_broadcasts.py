"""Broadcast messages (پیام همگانی) sent by the admin or a reseller."""
from alembic import op
import sqlalchemy as sa

revision = "0030_broadcasts"
down_revision = "0029_account_returns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sender_user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("audience", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_broadcasts"),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"], name="fk_broadcasts_sender_user_id_users"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_broadcasts_store_id_stores"),
    )
    op.create_index("ix_broadcasts_sender_user_id", "broadcasts", ["sender_user_id"])
    op.create_index("ix_broadcasts_store_id", "broadcasts", ["store_id"])


def downgrade():
    op.drop_index("ix_broadcasts_store_id", table_name="broadcasts")
    op.drop_index("ix_broadcasts_sender_user_id", table_name="broadcasts")
    op.drop_table("broadcasts")
