"""0016 – Sales pools: connection kind, customer-facing panel labels and per-pool package prices.

Changes
-------
* ``panel_groups.connection_kind``   VARCHAR(20) NOT NULL DEFAULT 'direct'  (direct | tunnel | softether)
* ``panel_group_members.label``      VARCHAR(80) NULL  (name shown to customers in a manual pool)
* ``pool_products``                  new table: which packages a pool sells, with optional price overrides
* backfill: every product that already has a default pool becomes a package of that pool (no price override)

Products without a default pool are NOT assigned automatically; they stay unsellable until an admin puts
them in a pool (there is no pool-less route any more).
"""
import sqlalchemy as sa
from alembic import op

revision = "0016_sales_pools"
down_revision = "0015_ticket_upgrade"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("panel_groups", sa.Column("connection_kind", sa.String(20), nullable=False, server_default="direct"))
    op.add_column("panel_group_members", sa.Column("label", sa.String(80), nullable=True))
    op.create_table(
        "pool_products",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("panel_group_id", sa.Uuid(), sa.ForeignKey("panel_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("main_price", sa.BigInteger(), nullable=True),
        sa.Column("reseller_price", sa.BigInteger(), nullable=True),
        sa.Column("is_listed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("panel_group_id", "product_id", name="uq_pool_products_pool_product"),
    )
    op.create_index("ix_pool_products_panel_group_id", "pool_products", ["panel_group_id"])
    op.create_index("ix_pool_products_product_id", "pool_products", ["product_id"])
    # Portable backfill (no gen_random_uuid): ids are generated in Python and bound through SQLAlchemy types.
    import uuid

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, default_panel_group_id FROM products WHERE default_panel_group_id IS NOT NULL")).fetchall()
    if rows:
        pool_products = sa.table(
            "pool_products",
            sa.column("id", sa.Uuid()), sa.column("panel_group_id", sa.Uuid()), sa.column("product_id", sa.Uuid()),
            sa.column("is_listed", sa.Boolean()), sa.column("sort", sa.Integer()),
        )
        op.bulk_insert(pool_products, [
            {"id": uuid.uuid4(), "panel_group_id": uuid.UUID(str(group_id)), "product_id": uuid.UUID(str(product_id)), "is_listed": True, "sort": 0}
            for product_id, group_id in rows
        ])


def downgrade():
    op.drop_index("ix_pool_products_product_id", table_name="pool_products")
    op.drop_index("ix_pool_products_panel_group_id", table_name="pool_products")
    op.drop_table("pool_products")
    op.drop_column("panel_group_members", "label")
    op.drop_column("panel_groups", "connection_kind")
