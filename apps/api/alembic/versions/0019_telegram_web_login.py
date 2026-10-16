"""0019 - Website login approved inside the Telegram bot.

Changes
-------
* ``telegram_login_sessions``  new table: one row per login attempt of the website (device-authorization flow).
  ``public_id`` is the value in the deep link/QR; ``secret_hash`` is the SHA-256 of the poll token that only the
  requesting browser knows; ``status`` is pending|scanned|approved|denied|expired|consumed.

Rows are short lived (minutes) and removed by the ``telegram_login_gc_job`` worker job one day after expiry.
No existing table changes.
"""
import sqlalchemy as sa
from alembic import op

revision = "0019_telegram_web_login"
down_revision = "0018_reseller_two_step"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telegram_login_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("public_id", sa.String(24), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("match_code", sa.String(2), nullable=False),
        sa.Column("decoys", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("req_ip", sa.String(64), nullable=True),
        sa.Column("req_device", sa.String(120), nullable=True),
        sa.Column("req_ua", sa.String(300), nullable=True),
        sa.Column("scanned_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("deny_reason", sa.String(40), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("public_id", name="uq_telegram_login_sessions_public_id"),
    )
    op.create_index("ix_telegram_login_sessions_store_id", "telegram_login_sessions", ["store_id"])
    op.create_index("ix_telegram_login_sessions_status", "telegram_login_sessions", ["status"])
    op.create_index("ix_telegram_login_sessions_expires_at", "telegram_login_sessions", ["expires_at"])


def downgrade():
    op.drop_index("ix_telegram_login_sessions_expires_at", table_name="telegram_login_sessions")
    op.drop_index("ix_telegram_login_sessions_status", table_name="telegram_login_sessions")
    op.drop_index("ix_telegram_login_sessions_store_id", table_name="telegram_login_sessions")
    op.drop_table("telegram_login_sessions")
