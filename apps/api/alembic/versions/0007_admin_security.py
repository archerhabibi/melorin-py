"""Admin 2FA replay state and role metadata.

Revision ID: 0007_admin_security
Revises: 0006_store_scoped_resellers
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_admin_security"
down_revision = "0006_store_scoped_resellers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("users")}
    if "admin_roles" not in columns:
        op.add_column("users", sa.Column("admin_roles", sa.JSON(), nullable=True))
        op.execute("UPDATE users SET admin_roles = '[]' WHERE admin_roles IS NULL")
    if "totp_last_counter" not in columns:
        op.add_column("users", sa.Column("totp_last_counter", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_last_counter")
    op.drop_column("users", "admin_roles")
