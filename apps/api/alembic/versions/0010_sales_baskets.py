"""Sales baskets: panel pools, naming policy and store overrides."""
from alembic import op
import sqlalchemy as sa

revision = "0010_sales_baskets"
down_revision = "0009_referral_first_reward_guard"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sales_baskets",
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("selection_mode", sa.String(20), nullable=False, server_default="automatic"),
        sa.Column("naming_mode", sa.String(20), nullable=False, server_default="automatic"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reseller_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sales_limit", sa.Integer(), nullable=True),
        sa.Column("sold_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "sales_basket_panels",
        sa.Column("basket_id", sa.Uuid(), sa.ForeignKey("sales_baskets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("panel_id", sa.Uuid(), sa.ForeignKey("panels.id"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sales_limit", sa.Integer(), nullable=True),
        sa.Column("sold_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("basket_id", "panel_id"),
    )
    op.create_table(
        "store_sales_baskets",
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("basket_id", sa.Uuid(), sa.ForeignKey("sales_baskets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("store_id", "basket_id"),
    )
    op.add_column("orders", sa.Column("basket_id", sa.Uuid(), sa.ForeignKey("sales_baskets.id"), nullable=True))
    op.add_column("orders", sa.Column("selected_panel_id", sa.Uuid(), sa.ForeignKey("panels.id"), nullable=True))
    op.add_column("orders", sa.Column("requested_account_name", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("orders", "requested_account_name")
    op.drop_column("orders", "selected_panel_id")
    op.drop_column("orders", "basket_id")
    op.drop_table("store_sales_baskets")
    op.drop_table("sales_basket_panels")
    op.drop_table("sales_baskets")
