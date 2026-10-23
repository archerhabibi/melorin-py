"""Account returns (مرجوعی): one row per returned purchase; also the per-user daily limit ledger."""
from alembic import op
import sqlalchemy as sa

revision = "0029_account_returns"
down_revision = "0028_admin_manual_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_returns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("vpn_account_id", sa.Uuid(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("limit_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_account_returns"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_account_returns_user_id_users"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_account_returns_store_id_stores"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_account_returns_order_id_orders"),
        sa.ForeignKeyConstraint(["vpn_account_id"], ["vpn_accounts.id"], name="fk_account_returns_vpn_account_id_vpn_accounts"),
        sa.UniqueConstraint("order_id", name="uq_account_returns_order_id"),
    )
    op.create_index("ix_account_returns_user_id", "account_returns", ["user_id"])
    op.create_index("ix_account_returns_store_id", "account_returns", ["store_id"])
    op.create_index("ix_account_returns_vpn_account_id", "account_returns", ["vpn_account_id"])


def downgrade():
    op.drop_index("ix_account_returns_vpn_account_id", table_name="account_returns")
    op.drop_index("ix_account_returns_store_id", table_name="account_returns")
    op.drop_index("ix_account_returns_user_id", table_name="account_returns")
    op.drop_table("account_returns")
