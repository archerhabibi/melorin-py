"""0014 – Short unguessable 6-char codes for orders and tickets.

Layout: 4-char sequential prefix + 2-char random suffix.
See melorin/core/codes.py for the encoding algorithm.

Changes
-------
* Creates PostgreSQL sequences ``order_number_seq`` and ``ticket_number_seq``.
* Shrinks ``orders.number`` VARCHAR(20) → VARCHAR(6)  (backfills first).
* Adds   ``tickets.number`` VARCHAR(6) UNIQUE NOT NULL (generated during migration).
* Upserts provisioning defaults: max_attempts=4, backoff_seconds=[5,7,10].
"""
from __future__ import annotations

import secrets

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision      = "0014_short_codes"
down_revision = "0013_product_default_panel_group"
branch_labels = None
depends_on    = None

_ALPHA = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_BASE  = len(_ALPHA)   # 32
_SW    = 4             # seq prefix width
_RW    = 2             # random suffix width


def _encode(n: int, width: int) -> str:
    out = []
    for _ in range(width):
        n, r = divmod(n, _BASE)
        out.append(_ALPHA[r])
    return "".join(reversed(out))


def _code(counter: int) -> str:
    """Deterministic prefix + fresh random suffix — same algorithm as codes.next_code."""
    return _encode(counter % (_BASE ** _SW), _SW) + "".join(
        secrets.choice(_ALPHA) for _ in range(_RW)
    )


def _unique_code(conn, table: str, id_col: str, row_id, counter: int) -> str:
    """Generate a collision-free code for *row_id* in *table*."""
    code = _code(counter)
    while conn.execute(
        text(f"SELECT 1 FROM {table} WHERE number = :n AND {id_col} != :id"),
        {"n": code, "id": row_id},
    ).fetchone():
        code = _code(counter + secrets.randbelow(100_000))
    return code


def upgrade() -> None:
    conn = op.get_bind()

    # ── sequences ──────────────────────────────────────────────────────────
    conn.execute(text("CREATE SEQUENCE IF NOT EXISTS order_number_seq  START 1"))
    conn.execute(text("CREATE SEQUENCE IF NOT EXISTS ticket_number_seq START 1"))

    # ── orders.number: backfill then shrink VARCHAR(20) → VARCHAR(6) ───────
    # Step 1: temporarily allow NULL so ALTER TYPE succeeds without rewriting
    op.alter_column(
        "orders", "number",
        existing_type=sa.String(20),
        type_=sa.String(6),
        nullable=True,
        postgresql_using="NULL",
    )
    # Step 2: assign fresh 6-char codes to every existing row
    rows = conn.execute(
        text("SELECT id FROM orders ORDER BY created_at ASC NULLS LAST")
    ).fetchall()
    for i, (oid,) in enumerate(rows, start=1):
        code = _unique_code(conn, "orders", "id", oid, i)
        conn.execute(text("UPDATE orders SET number = :n WHERE id = :id"),
                     {"n": code, "id": oid})
        conn.execute(text("SELECT nextval('order_number_seq')"))
    # Step 3: restore NOT NULL
    op.alter_column("orders", "number",
                    existing_type=sa.String(6), nullable=False)

    # ── tickets.number: add column, backfill, add constraints ──────────────
    op.add_column("tickets", sa.Column("number", sa.String(6), nullable=True))
    ticket_rows = conn.execute(
        text("SELECT id FROM tickets ORDER BY created_at ASC NULLS LAST")
    ).fetchall()
    for i, (tid,) in enumerate(ticket_rows, start=1):
        code = _unique_code(conn, "tickets", "id", tid, i)
        conn.execute(text("UPDATE tickets SET number = :n WHERE id = :id"),
                     {"n": code, "id": tid})
        conn.execute(text("SELECT nextval('ticket_number_seq')"))
    op.alter_column("tickets", "number",
                    existing_type=sa.String(6), nullable=False)
    # Single unique index: matches the model (unique=True, index=True).
    op.create_index("ix_tickets_number", "tickets", ["number"], unique=True)

    # ── provisioning policy defaults ───────────────────────────────────────
    # These are the DB-stored overrides; the Python DEFAULTS dict is the
    # in-code fallback. Writing them here ensures a fresh install uses the
    # new policy even before any admin edits the settings UI.
    # system_settings.id is UUID NOT NULL with no server default, so supply it.
    conn.execute(text("""
        INSERT INTO system_settings (id, key, value)
        VALUES
            (gen_random_uuid(), 'provisioning.max_attempts',   '4'::json),
            (gen_random_uuid(), 'provisioning.backoff_seconds', '[5,7,10]'::json)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
    """))


def downgrade() -> None:
    conn = op.get_bind()
    # Remove the settings rows (Python DEFAULTS will take over)
    conn.execute(text(
        "DELETE FROM system_settings "
        "WHERE key IN ('provisioning.max_attempts', 'provisioning.backoff_seconds')"
    ))
    op.drop_index("ix_tickets_number", table_name="tickets")
    op.drop_column("tickets", "number")
    op.alter_column(
        "orders", "number",
        existing_type=sa.String(6),
        type_=sa.String(20),
        nullable=False,
    )
    conn.execute(text("DROP SEQUENCE IF EXISTS ticket_number_seq"))
    conn.execute(text("DROP SEQUENCE IF EXISTS order_number_seq"))
