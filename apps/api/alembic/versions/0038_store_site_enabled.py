"""Per-store website switch: reseller stores default to site OFF, bot ON; the Main Store keeps both on.

``stores.site_enabled`` is new. Existing reseller stores are switched off by this migration (the product is not released yet,
so no reseller depends on the site); the Main Store and any future store created outside the reseller flow stay on.
"""

import sqlalchemy as sa
from alembic import op

revision = "0038_store_site_enabled"
down_revision = "0037_commission_reward_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("site_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.execute(sa.text("UPDATE stores SET site_enabled = false WHERE kind = 'reseller'"))


def downgrade() -> None:
    op.drop_column("stores", "site_enabled")
