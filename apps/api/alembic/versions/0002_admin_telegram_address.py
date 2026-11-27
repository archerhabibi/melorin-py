"""Move the admin's Telegram ID from an identity of the admin account to a system setting.

The admin's Telegram ID is only an alert address (``melorin.core.admin_telegram``). Until now it was stored as a ``telegram``
identity of the admin user, which made the bot refuse that Telegram account as a customer. The address moves to the setting
``admin.telegram_id:<admin user id>`` and the identity row is deleted, so the same Telegram account signs in as an ordinary customer.
Only identities of super admins are touched. Downgrade puts the identity back where the address is still unique.
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0002_admin_telegram_address"
down_revision = "0001_initial_baseline"
branch_labels = None
depends_on = None

_PREFIX = "admin.telegram_id:"


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT i.id, i.user_id, i.subject FROM identities i JOIN users u ON u.id = i.user_id "
            "WHERE i.provider = 'telegram' AND u.is_super_admin = :t"
        ),
        {"t": True},
    ).fetchall()
    for ident_id, user_id, subject in rows:
        key = f"{_PREFIX}{uuid.UUID(str(user_id))}"
        exists = bind.execute(sa.text("SELECT 1 FROM system_settings WHERE key = :k"), {"k": key}).first()
        if not exists:
            bind.execute(
                sa.text("INSERT INTO system_settings (id, key, value, created_at, updated_at) VALUES (:id, :k, :v, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                {"id": uuid.uuid4(), "k": key, "v": json.dumps(subject)},
            )
        bind.execute(sa.text("DELETE FROM identities WHERE id = :i"), {"i": ident_id})


def downgrade() -> None:
    bind = op.get_bind()
    for key, value in bind.execute(sa.text("SELECT key, value FROM system_settings WHERE key LIKE :p"), {"p": _PREFIX + "%"}).fetchall():
        subject = json.loads(value) if isinstance(value, str) else value
        user_id = key[len(_PREFIX) :]
        taken = bind.execute(sa.text("SELECT 1 FROM identities WHERE provider = 'telegram' AND subject = :s"), {"s": str(subject)}).first()
        if not taken:
            bind.execute(
                sa.text(
                    "INSERT INTO identities (id, user_id, provider, subject, status, created_at) "
                    "VALUES (:id, :u, 'telegram', :s, 'active', CURRENT_TIMESTAMP)"
                ),
                {"id": uuid.uuid4(), "u": user_id, "s": str(subject)},
            )
        bind.execute(sa.text("DELETE FROM system_settings WHERE key = :k"), {"k": key})
