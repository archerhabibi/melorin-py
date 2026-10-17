"""Per-package switch for resellers + every package in every sales bundle.

* ``products.reseller_enabled`` (default true): the main store can stop resellers from selling a package without
  disabling it for itself. Disabling a package for the main store (``is_active``) hides it from resellers too.
* Packages have no default bundle any more: every sellable package is listed in every bundle. Missing
  ``bundle_products`` rows are added (listed, no price override). Existing rows are never touched, so prices and
  an admin's "hidden in this bundle" decision stay as they are.
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_product_reseller_switch"
down_revision = "0023_link_resellers_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("products", sa.Column("reseller_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute(sa.text("""
        INSERT INTO bundle_products (id, bundle_id, product_id, main_price, reseller_price, is_listed, sort, created_at, updated_at)
        SELECT md5('bp:' || b.id::text || ':' || p.id::text)::uuid, b.id, p.id, NULL, NULL, TRUE, 0, now(), now()
        FROM bundles b
        CROSS JOIN products p
        WHERE p.is_test = FALSE
          AND p.archived_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM bundle_products bp WHERE bp.bundle_id = b.id AND bp.product_id = p.id)
    """))


def downgrade():
    op.drop_column("products", "reseller_enabled")
