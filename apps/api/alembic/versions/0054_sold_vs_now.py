"""R9/R10: sold entitlement vs panel "now"; the copied panel columns are dropped.

Melorin is a mediator. ``vpn_accounts.expires_at`` / ``traffic_limit_bytes`` become ``sold_expires_at`` / ``sold_traffic_bytes``
(what Melorin sold or last applied). Used traffic, remote status, last seen, lifetime usage and the subscription link are read from
the panel; only the link *as delivered* is kept, as ``delivery_snapshot``. Melorin has not been released, so nothing needs a
"one release without readers" wait; the delivery snapshot is back-filled from the old columns where they exist.
"""

import sqlalchemy as sa
from alembic import op

revision = "0054_sold_vs_now"
down_revision = "0053_mediator_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_vpn_accounts_expires_at", table_name="vpn_accounts")
    with op.batch_alter_table("vpn_accounts") as batch:
        batch.add_column(sa.Column("delivery_snapshot", sa.JSON(), nullable=True))
        batch.alter_column("expires_at", new_column_name="sold_expires_at")
        batch.alter_column("traffic_limit_bytes", new_column_name="sold_traffic_bytes")
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, subscription_url, links FROM vpn_accounts WHERE subscription_url IS NOT NULL OR links IS NOT NULL"))
    import json

    for row in rows.fetchall():
        links = row.links
        if isinstance(links, str):
            try:
                links = json.loads(links)
            except ValueError:
                links = None
        snap = {"subscription_url": row.subscription_url, "links": links, "taken_at": None}
        bind.execute(sa.text("UPDATE vpn_accounts SET delivery_snapshot = :s WHERE id = :i").bindparams(
            sa.bindparam("s", type_=sa.JSON()), sa.bindparam("i")), {"s": snap, "i": row.id})
    with op.batch_alter_table("vpn_accounts") as batch:
        for col in ("traffic_used_bytes", "subscription_url", "links", "remote_status", "online_at", "lifetime_used_traffic"):
            batch.drop_column(col)
    op.create_index("ix_vpn_accounts_sold_expires_at", "vpn_accounts", ["sold_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_vpn_accounts_sold_expires_at", table_name="vpn_accounts")
    with op.batch_alter_table("vpn_accounts") as batch:
        batch.add_column(sa.Column("lifetime_used_traffic", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("online_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("remote_status", sa.String(20), nullable=True))
        batch.add_column(sa.Column("links", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("subscription_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("traffic_used_bytes", sa.BigInteger(), nullable=True, server_default="0"))
        batch.alter_column("sold_traffic_bytes", new_column_name="traffic_limit_bytes")
        batch.alter_column("sold_expires_at", new_column_name="expires_at")
        batch.drop_column("delivery_snapshot")
    op.create_index("ix_vpn_accounts_expires_at", "vpn_accounts", ["expires_at"])
