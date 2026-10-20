"""Channel binding: refresh-token families and web-handoff codes remember the store they were opened for.

Existing refresh tokens have no binding (``channel`` NULL) and are refused at rotation, so every user signs in again once
through the right channel. The project has no production deployment yet, so this costs nothing; the rows stay for audit.
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_channel_binding"
down_revision = "0026_merge_reseller_credit"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("refresh_tokens") as b:
        b.add_column(sa.Column("channel", sa.String(10), nullable=True))
        b.add_column(sa.Column("store_id", sa.Uuid(), nullable=True))
        b.create_foreign_key("fk_refresh_tokens_store_id_stores", "stores", ["store_id"], ["id"])
    with op.batch_alter_table("verification_codes") as b:
        b.add_column(sa.Column("store_id", sa.Uuid(), nullable=True))
        b.create_foreign_key("fk_verification_codes_store_id_stores", "stores", ["store_id"], ["id"])


def downgrade():
    with op.batch_alter_table("verification_codes") as b:
        b.drop_constraint("fk_verification_codes_store_id_stores", type_="foreignkey")
        b.drop_column("store_id")
    with op.batch_alter_table("refresh_tokens") as b:
        b.drop_constraint("fk_refresh_tokens_store_id_stores", type_="foreignkey")
        b.drop_column("store_id")
        b.drop_column("channel")
