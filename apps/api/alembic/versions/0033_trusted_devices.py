"""0033 - Automatic identity verification: trusted devices.

Changes
-------
* ``trusted_devices``  new table: browsers that were approved once through the Telegram bot (SHA-256 of the device key).
* ``telegram_login_sessions``  gains ``device_key_hash``, ``remember`` and ``auto_level``.
"""
import sqlalchemy as sa
from alembic import op

revision = "0033_trusted_devices"
down_revision = "0032_bank_sms_auto_verify"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trusted_devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("last_ip", sa.String(64), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_trusted_devices_key_hash"),
    )
    op.create_index("ix_trusted_devices_user_id", "trusted_devices", ["user_id"])
    op.create_index("ix_trusted_devices_store_id", "trusted_devices", ["store_id"])
    op.create_index("ix_trusted_devices_telegram_id", "trusted_devices", ["telegram_id"])
    op.create_index("ix_trusted_devices_expires_at", "trusted_devices", ["expires_at"])
    with op.batch_alter_table("telegram_login_sessions") as b:
        b.add_column(sa.Column("device_key_hash", sa.String(64), nullable=True))
        b.add_column(sa.Column("remember", sa.Boolean(), nullable=False, server_default=sa.true()))
        b.add_column(sa.Column("auto_level", sa.String(12), nullable=True))
        b.create_index("ix_telegram_login_sessions_device_key_hash", ["device_key_hash"])


def downgrade():
    with op.batch_alter_table("telegram_login_sessions") as b:
        b.drop_index("ix_telegram_login_sessions_device_key_hash")
        b.drop_column("auto_level")
        b.drop_column("remember")
        b.drop_column("device_key_hash")
    op.drop_table("trusted_devices")
