"""Create orders.vpn_account_id FK that CreateTable omits (circular use_alter reference).

Revision ID: 0005_orders_vpn_fk
Revises: 0004_f027_f030
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_orders_vpn_fk"
down_revision = "0004_f027_f030"
branch_labels = None
depends_on = None

FK_NAME = "fk_orders_vpn_account_id_vpn_accounts"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if any(fk["referred_table"] == "vpn_accounts" and fk["constrained_columns"] == ["vpn_account_id"] for fk in inspector.get_foreign_keys("orders")):
        return
    op.create_foreign_key(FK_NAME, "orders", "vpn_accounts", ["vpn_account_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint(FK_NAME, "orders", type_="foreignkey")
