"""Publish existing active products in the main store.

The admin UI now publishes new products automatically. This backfills products
created before that behavior so an existing deployment is not left empty.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_backfill_main_products"
down_revision = "0010_sales_baskets"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("""
        INSERT INTO store_products (id, store_id, product_id, is_enabled, is_listed, customer_price, created_at, updated_at)
        SELECT md5(s.id::text || ':' || p.id::text)::uuid, s.id, p.id, TRUE, TRUE, NULL, now(), now()
        FROM stores s
        CROSS JOIN products p
        WHERE s.kind = 'main'
          AND s.status = 'active'
          AND p.is_active = TRUE
          AND p.archived_at IS NULL
          AND p.is_test = FALSE
          AND NOT EXISTS (
              SELECT 1
              FROM store_products sp
              WHERE sp.store_id = s.id AND sp.product_id = p.id
          )
    """))


def downgrade():
    # Deliberately leave backfilled availability rows in place. Removing them
    # could delete an admin's later pricing or visibility decision.
    pass
