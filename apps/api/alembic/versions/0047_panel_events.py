"""PasarGuard roadmap Phase 2 (PG-03): real-time events pushed by the panel.

* ``panels.webhook_secret_enc`` / ``webhook_last_at`` / ``webhook_connected_at``  the shared secret (encrypted), last accepted
                                               delivery and when an admin connected events
* ``panel_events``                             every received event: audit trail and work queue in one. UNIQUE (panel_id, dedup_key)
                                               makes a replayed delivery a no-op.

Additive and nullable/defaulted: nothing changes until a panel is explicitly connected to events.
"""

import sqlalchemy as sa
from alembic import op

revision = "0047_panel_events"
down_revision = "0046_store_vpn_notice_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("panels", sa.Column("webhook_secret_enc", sa.Text(), nullable=True))
    op.add_column("panels", sa.Column("webhook_last_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("panels", sa.Column("webhook_connected_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "panel_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("panel_id", sa.Uuid(), sa.ForeignKey("panels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dedup_key", sa.String(200), nullable=False),
        sa.Column("event_id", sa.String(100), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("username", sa.String(128), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(200), nullable=True),
        sa.Column("vpn_account_id", sa.Uuid(), sa.ForeignKey("vpn_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("panel_id", "dedup_key", name="uq_panel_events_dedup"),
    )
    op.create_index("ix_panel_events_panel_id", "panel_events", ["panel_id"])
    op.create_index("ix_panel_events_queue", "panel_events", ["status", "available_at"])
    op.create_index("ix_panel_events_received_at", "panel_events", ["received_at"])


def downgrade() -> None:
    op.drop_table("panel_events")
    op.drop_column("panels", "webhook_connected_at")
    op.drop_column("panels", "webhook_last_at")
    op.drop_column("panels", "webhook_secret_enc")
