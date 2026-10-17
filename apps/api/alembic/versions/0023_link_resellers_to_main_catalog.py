"""Connect existing reseller stores to the main packages and sales bundles.

Reseller stores created before the automatic linking had no ``store_products`` / ``store_bundles`` rows, so their
price table was empty. This adds the missing rows (enabled, listed, no price). Existing rows are never touched, so
an admin's per-store decision and a reseller's own prices stay as they are.
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_link_resellers_catalog"
down_revision = "0022_panel_group_to_bundle"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("""
        INSERT INTO store_products (id, store_id, product_id, is_enabled, is_listed, customer_price, created_at, updated_at)
        SELECT md5('link:' || s.id::text || ':' || p.id::text)::uuid, s.id, p.id, TRUE, TRUE, NULL, now(), now()
        FROM stores s
        CROSS JOIN products p
        WHERE s.kind = 'reseller'
          AND p.is_active = TRUE
          AND p.archived_at IS NULL
          AND p.is_test = FALSE
          AND NOT EXISTS (SELECT 1 FROM store_products sp WHERE sp.store_id = s.id AND sp.product_id = p.id)
    """))
    op.execute(sa.text("""
        INSERT INTO store_bundles (id, store_id, bundle_id, is_enabled, created_at, updated_at)
        SELECT md5('link:' || s.id::text || ':' || b.id::text)::uuid, s.id, b.id, TRUE, now(), now()
        FROM stores s
        CROSS JOIN bundles b
        WHERE s.kind = 'reseller'
          AND b.reseller_enabled = TRUE
          AND NOT EXISTS (SELECT 1 FROM store_bundles sb WHERE sb.store_id = s.id AND sb.bundle_id = b.id)
    """))


def downgrade():
    # Deliberately leave the rows: removing them could delete a reseller's pricing or an admin's decision.
    pass
