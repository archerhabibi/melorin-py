"""0020 - Reseller retail price per sales pool.

Changes
-------
* ``store_pool_prices``  new table: one row per (reseller store, sales pool, package) that has its own retail price.
  A row overrides ``store_products.customer_price`` (the store-wide price) for that pool only. No row = the pool
  uses the store-wide price, exactly as before this migration, so existing stores keep selling at the same prices.

No existing table or column changes; downgrade only drops the new table.
"""
import sqlalchemy as sa
from alembic import op

revision = "0020_store_pool_prices"
down_revision = "0019_telegram_web_login"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "store_pool_prices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("panel_group_id", sa.Uuid(), sa.ForeignKey("panel_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_price", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("store_id", "panel_group_id", "product_id"),
    )
    op.create_index("ix_store_pool_prices_store_id", "store_pool_prices", ["store_id"])
    op.create_index("ix_store_pool_prices_panel_group_id", "store_pool_prices", ["panel_group_id"])
    op.create_index("ix_store_pool_prices_product_id", "store_pool_prices", ["product_id"])


def downgrade():
    op.drop_index("ix_store_pool_prices_product_id", table_name="store_pool_prices")
    op.drop_index("ix_store_pool_prices_panel_group_id", table_name="store_pool_prices")
    op.drop_index("ix_store_pool_prices_store_id", table_name="store_pool_prices")
    op.drop_table("store_pool_prices")
