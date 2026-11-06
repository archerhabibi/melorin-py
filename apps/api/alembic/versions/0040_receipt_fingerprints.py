"""Duplicate card-receipt detection: one fingerprint row (sha256 + Telegram file_unique_id) per receipt upload.

* ``payment_receipt_fingerprints`` - payment_id, store_id, file_unique_id NULL, sha256 NULL, created_at; indexed on both hashes.
* Backfill: every receipt already attached to a payment gets a sha256 row from ``file_objects``, so images that were
  paid with before this release are still recognised when somebody uploads them again.

The per-store policy (``warn`` default | ``block``) lives in ``system_settings`` (``payments.receipt_dup.<store_id>``); no column is needed.
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0040_receipt_fingerprints"
down_revision = "0039_target_selection"
branch_labels = None
depends_on = None

_CHUNK = 500


def upgrade() -> None:
    table = op.create_table(
        "payment_receipt_fingerprints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("file_unique_id", sa.String(length=128), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_payment_receipt_fingerprints_payment_id", "payment_receipt_fingerprints", ["payment_id"])
    op.create_index("ix_payment_receipt_fingerprints_store_id", "payment_receipt_fingerprints", ["store_id"])
    op.create_index("ix_receipt_fp_sha256", "payment_receipt_fingerprints", ["sha256"])
    op.create_index("ix_receipt_fp_file_unique_id", "payment_receipt_fingerprints", ["file_unique_id"])

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT p.id AS payment_id, p.store_id AS store_id, f.sha256 AS sha256, p.created_at AS created_at "
            "FROM payments p JOIN file_objects f ON f.id = p.receipt_file_id WHERE f.sha256 IS NOT NULL"
        )
    ).fetchall()
    batch = [
        {"id": uuid.uuid4(), "payment_id": r.payment_id, "store_id": r.store_id, "sha256": r.sha256, "created_at": r.created_at}
        for r in rows
    ]
    for i in range(0, len(batch), _CHUNK):
        op.bulk_insert(table, batch[i : i + _CHUNK])


def downgrade() -> None:
    op.drop_index("ix_receipt_fp_file_unique_id", table_name="payment_receipt_fingerprints")
    op.drop_index("ix_receipt_fp_sha256", table_name="payment_receipt_fingerprints")
    op.drop_index("ix_payment_receipt_fingerprints_store_id", table_name="payment_receipt_fingerprints")
    op.drop_index("ix_payment_receipt_fingerprints_payment_id", table_name="payment_receipt_fingerprints")
    op.drop_table("payment_receipt_fingerprints")
