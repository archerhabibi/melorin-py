"""Auto target selection: a server (UI: مقصد) carries its own group/inbound target, bundles get a balancing method.

* ``servers.target``            JSON NULL  - {"group_ids": [..]} | {"user_template_id": n} | {"inbound_ids": [..]}; NULL = inherit ``panel.config``
* ``servers.last_assigned_at``  DateTime NULL - round_robin ordering key (oldest first, NULL first)
* ``bundles.balancing``         round_robin (default) | least_fill | fill_first
* ``orders.allocated_server_id`` the destination pinned on the first allocation, so every retry reuses it
* ``vpn_accounts.placement``    JSON NULL  - immutable audit snapshot of where the account was created

Every new column is nullable or has a safe default, so existing rows keep working. The project is not released: the former
"least active" automatic rule is gone, every bundle is round_robin.
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_target_selection"
down_revision = "0038_store_site_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("servers") as b:
        b.add_column(sa.Column("target", sa.JSON(), nullable=True))
        b.add_column(sa.Column("last_assigned_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("bundles") as b:
        b.add_column(sa.Column("balancing", sa.String(length=20), nullable=False, server_default="round_robin"))
    with op.batch_alter_table("orders") as b:
        b.add_column(sa.Column("allocated_server_id", sa.Uuid(), nullable=True))
        b.create_foreign_key("fk_orders_allocated_server_id_servers", "servers", ["allocated_server_id"], ["id"])
    with op.batch_alter_table("vpn_accounts") as b:
        b.add_column(sa.Column("placement", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE bundles SET balancing = 'round_robin'"))


def downgrade() -> None:
    with op.batch_alter_table("vpn_accounts") as b:
        b.drop_column("placement")
    with op.batch_alter_table("orders") as b:
        b.drop_constraint("fk_orders_allocated_server_id_servers", type_="foreignkey")
        b.drop_column("allocated_server_id")
    with op.batch_alter_table("bundles") as b:
        b.drop_column("balancing")
    with op.batch_alter_table("servers") as b:
        b.drop_column("last_assigned_at")
        b.drop_column("target")
