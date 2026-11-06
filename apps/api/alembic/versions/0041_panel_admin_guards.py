"""Database guards for per-store panel admins.

* ``uq_panel_admins_panel_username``         one panel login belongs to ONE store (a clash would mix two stores' accounts)
* ``uq_panel_admin_request_one_pending``     one pending "Profile & contact" change request per store, enforced by the database

Additive: two indexes. Older duplicate *pending* requests (possible only through the former check-then-insert race) are cancelled,
newest kept. A duplicate username is NOT touched: it would mean two stores already share a panel login, which needs a human
decision (the migration stops with the clashing names instead of guessing).
"""

import sqlalchemy as sa
from alembic import op

revision = "0041_panel_admin_guards"
down_revision = "0040_panel_admins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    clash = bind.execute(
        sa.text("SELECT panel_id, username, COUNT(*) FROM panel_admins GROUP BY panel_id, username HAVING COUNT(*) > 1")
    ).fetchall()
    if clash:
        names = ", ".join(f"{row[1]} (panel {row[0]}, x{row[2]})" for row in clash)
        raise RuntimeError(f"panel_admins: several stores share one panel login: {names}. Resolve them, then re-run the migration.")
    # keep the newest pending request of each store (ties broken by id), cancel the older ones
    pending = bind.execute(
        sa.text("SELECT id, store_id FROM panel_admin_change_requests WHERE status = 'pending' ORDER BY created_at DESC, id DESC")
    ).fetchall()
    seen: set = set()
    for request_id, store_id in pending:
        if store_id in seen:
            bind.execute(sa.text("UPDATE panel_admin_change_requests SET status = 'cancelled' WHERE id = :id"), {"id": request_id})
        seen.add(store_id)
    op.create_index("uq_panel_admins_panel_username", "panel_admins", ["panel_id", "username"], unique=True)
    op.create_index(
        "uq_panel_admin_request_one_pending",
        "panel_admin_change_requests",
        ["store_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_panel_admin_request_one_pending", table_name="panel_admin_change_requests")
    op.drop_index("uq_panel_admins_panel_username", table_name="panel_admins")
