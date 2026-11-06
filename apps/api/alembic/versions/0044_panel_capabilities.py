"""Panel capability snapshot (PasarGuard roadmap PG-00).

* ``panels.capabilities``            JSON, NULL = never probed. ``{"flags": {...}, "declared": {...}, "denied": {...}, "role", "source", ...}``
* ``panels.capabilities_checked_at`` when the snapshot was taken (the health job refreshes it hourly)

Additive and nullable: existing panels keep working exactly as before. The admin API falls back to the adapter's own declaration
until the first probe, so no backfill is needed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0044_panel_capabilities"
down_revision = "0043_receipt_fingerprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("panels", sa.Column("capabilities", sa.JSON(), nullable=True))
    op.add_column("panels", sa.Column("capabilities_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("panels", "capabilities_checked_at")
    op.drop_column("panels", "capabilities")
