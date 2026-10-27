"""0035 - Automatic approval and continuous re-verification of reseller identity.

Changes
-------
* ``reseller_applications`` gains ``auto_approved``, ``recheck_next_at``, ``recheck_failures``, ``recheck_error`` and
  ``identity_lost_at`` (the schedule and outcome of the periodic re-check of an approved store's domain proof and bot).
* Approved applications that already proved their domain are scheduled for a first re-check right away.
"""
import sqlalchemy as sa
from alembic import op

revision = "0035_reseller_identity_lifecycle"
down_revision = "0034_reseller_auto_verify"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reseller_applications", sa.Column("auto_approved", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("reseller_applications", sa.Column("recheck_next_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reseller_applications", sa.Column("recheck_failures", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("reseller_applications", sa.Column("recheck_error", sa.String(200), nullable=True))
    op.add_column("reseller_applications", sa.Column("identity_lost_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE reseller_applications SET recheck_next_at = CURRENT_TIMESTAMP "
        "WHERE status = 'approved' AND store_id IS NOT NULL AND domain_verified_at IS NOT NULL"
    )


def downgrade():
    for c in ("identity_lost_at", "recheck_error", "recheck_failures", "recheck_next_at", "auto_approved"):
        op.drop_column("reseller_applications", c)
