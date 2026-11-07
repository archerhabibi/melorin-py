"""PasarGuard Phase 1 follow-up (PG-06): per-store VPN notice settings.

* ``stores.vpn_notice_settings`` (JSON, nullable)   today ``{"traffic_low_levels": [80, 90]}``; NULL = platform defaults

Additive and nullable: every existing store keeps the 80% / 90% warnings until an admin changes them.
"""

import sqlalchemy as sa
from alembic import op

revision = "0046_store_vpn_notice_settings"
down_revision = "0045_panel_ops_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("vpn_notice_settings", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("stores", "vpn_notice_settings")
