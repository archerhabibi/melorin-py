"""F027-F030 reseller invariant, panel TLS, and health diagnostics.

Revision ID: 0004_f027_f030
Revises: 0003_f001_f010
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_f027_f030"
down_revision = "0003_f001_f010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "uq_reseller_application_pending_user" in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("reseller_applications")}:
        return
    op.create_index(
        "uq_reseller_application_pending_user",
        "reseller_applications",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_reseller_application_pending_user", table_name="reseller_applications")
