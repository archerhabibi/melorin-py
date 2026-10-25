"""Card-to-card auto verification: bank SMS sources and received SMS messages."""
from alembic import op
import sqlalchemy as sa

revision = "0032_bank_sms_auto_verify"
down_revision = "0031_event_center_health"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bank_sms_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("bank", sa.String(30), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_verify", sa.Boolean(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("token_hint", sa.String(8), nullable=True),
        sa.Column("senders", sa.JSON(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_bank_sms_sources"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_bank_sms_sources_store_id_stores"),
        sa.UniqueConstraint("store_id", name="uq_bank_sms_sources_store_id"),
    )
    op.create_index("ix_bank_sms_sources_store_id", "bank_sms_sources", ["store_id"])
    op.create_table(
        "bank_sms_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("serial", sa.String(64), nullable=True),
        sa.Column("direction", sa.String(12), nullable=True),
        sa.Column("amount_rial", sa.BigInteger(), nullable=True),
        sa.Column("balance_rial", sa.BigInteger(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sender", sa.String(64), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("matched_by", sa.String(10), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("balance_gap", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_bank_sms_messages"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_bank_sms_messages_store_id_stores"),
        sa.ForeignKeyConstraint(["source_id"], ["bank_sms_sources.id"], name="fk_bank_sms_messages_source_id_bank_sms_sources"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name="fk_bank_sms_messages_payment_id_payments"),
        sa.UniqueConstraint("store_id", "fingerprint", name="uq_bank_sms_messages_store_id_fingerprint"),
        sa.UniqueConstraint("payment_id", name="uq_bank_sms_messages_payment_id"),
    )
    op.create_index("ix_bank_sms_messages_store_id", "bank_sms_messages", ["store_id"])
    op.create_index("ix_bank_sms_messages_occurred_at", "bank_sms_messages", ["occurred_at"])
    op.create_index("ix_bank_sms_messages_status", "bank_sms_messages", ["status"])


def downgrade():
    op.drop_index("ix_bank_sms_messages_status", table_name="bank_sms_messages")
    op.drop_index("ix_bank_sms_messages_occurred_at", table_name="bank_sms_messages")
    op.drop_index("ix_bank_sms_messages_store_id", table_name="bank_sms_messages")
    op.drop_table("bank_sms_messages")
    op.drop_index("ix_bank_sms_sources_store_id", table_name="bank_sms_sources")
    op.drop_table("bank_sms_sources")
