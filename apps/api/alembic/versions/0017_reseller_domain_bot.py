"""0017 – Reseller applications carry the store domain and the reseller bot.

Changes
-------
* ``stores.domain``                       VARCHAR(255) NULL, unique (public hostname of the store)
* ``reseller_applications.domain``        requested hostname
* ``reseller_applications.bot_token_enc`` encrypted bot token (never exposed by the API)
* ``reseller_applications.bot_key``       stable ``tg:<bot id>`` identity (uniqueness while pending)
* ``reseller_applications.bot_username``  / ``bot_verified`` result of the Telegram getMe check
* ``reseller_applications.review_reason`` admin note shown to the applicant on rejection

Existing applications keep NULL in the new columns; only new applications must provide them.
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_reseller_domain_bot"
down_revision = "0016_sales_pools"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stores", sa.Column("domain", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_stores_domain", "stores", ["domain"])
    op.add_column("reseller_applications", sa.Column("domain", sa.String(255), nullable=True))
    op.add_column("reseller_applications", sa.Column("bot_token_enc", sa.String(500), nullable=True))
    op.add_column("reseller_applications", sa.Column("bot_key", sa.String(120), nullable=True))
    op.add_column("reseller_applications", sa.Column("bot_username", sa.String(100), nullable=True))
    op.add_column("reseller_applications", sa.Column("bot_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("reseller_applications", sa.Column("review_reason", sa.String(500), nullable=True))
    op.create_index("uq_reseller_application_pending_domain", "reseller_applications", ["domain"], unique=True, postgresql_where=sa.text("status = 'pending'"))
    op.create_index("uq_reseller_application_pending_bot", "reseller_applications", ["bot_key"], unique=True, postgresql_where=sa.text("status = 'pending'"))


def downgrade():
    op.drop_index("uq_reseller_application_pending_bot", table_name="reseller_applications")
    op.drop_index("uq_reseller_application_pending_domain", table_name="reseller_applications")
    for c in ("review_reason", "bot_verified", "bot_username", "bot_key", "bot_token_enc", "domain"):
        op.drop_column("reseller_applications", c)
    op.drop_constraint("uq_stores_domain", "stores", type_="unique")
    op.drop_column("stores", "domain")
