"""0018 - Two-step reseller applications (request first, domain + bot token after approval).

Changes
-------
* ``reseller_applications.approved_debt_limit`` BIGINT NULL - debt limit chosen by the admin when a request that has no
  domain/bot yet is approved; used when the applicant later supplies the details and the store is created.
* New status value ``awaiting_details`` (status is a plain VARCHAR(20); no DDL needed).

Existing rows are untouched. Applications filed with domain + bot token (web form) behave exactly as before.
"""
import sqlalchemy as sa
from alembic import op

revision = "0018_reseller_two_step"
down_revision = "0017_reseller_domain_bot"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reseller_applications", sa.Column("approved_debt_limit", sa.BigInteger(), nullable=True))


def downgrade():
    op.execute("UPDATE reseller_applications SET status = 'cancelled' WHERE status = 'awaiting_details'")
    op.drop_column("reseller_applications", "approved_debt_limit")
