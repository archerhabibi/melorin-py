"""0034 - Automatic identity verification of reseller applications.

Changes
-------
* ``reseller_applications`` gains ``domain_verified_at``, ``domain_method``, ``verify_attempts``, ``verify_next_at``
  and ``verify_error`` (proof of domain control and the retry schedule of the background verifier).
"""
import sqlalchemy as sa
from alembic import op

revision = "0034_reseller_auto_verify"
down_revision = "0033_trusted_devices"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reseller_applications", sa.Column("domain_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reseller_applications", sa.Column("domain_method", sa.String(10), nullable=True))
    op.add_column("reseller_applications", sa.Column("verify_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("reseller_applications", sa.Column("verify_next_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reseller_applications", sa.Column("verify_error", sa.String(200), nullable=True))


def downgrade():
    for c in ("verify_error", "verify_next_at", "verify_attempts", "domain_method", "domain_verified_at"):
        op.drop_column("reseller_applications", c)
