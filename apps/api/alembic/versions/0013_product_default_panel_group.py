"""Products point to their default panel group so every channel allocates the same way."""

import sqlalchemy as sa
from alembic import op

revision = "0013_product_default_panel_group"
down_revision = "0012_baskets_to_panel_groups"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("products", sa.Column("default_panel_group_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_products_default_panel_group", "products", "panel_groups", ["default_panel_group_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_products_default_panel_group_id", "products", ["default_panel_group_id"])


def downgrade():
    op.drop_index("ix_products_default_panel_group_id", table_name="products")
    op.drop_constraint("fk_products_default_panel_group", "products", type_="foreignkey")
    op.drop_column("products", "default_panel_group_id")
