"""PasarGuard roadmap Phase 3 (PG-08 capacity, PG-09 templates / prepaid renewal).

* ``servers``  real destination state: ``sellable`` (sell-guard) + reason, ``destination_health`` (JSON), ``panel_total_users``,
               ``capacity_source`` (melorin | panel), ``capacity_alert_level``, ``capacity_checked_at``
* ``orders.renewal_mode``  ``replace`` (today's behaviour, default) | ``queue`` (prepaid next plan)
* ``vpn_accounts.queued_plan``  the package queued on the panel for this account
* ``product_templates``  product <-> panel user template mapping

Additive and defaulted: every existing row keeps today's behaviour (sellable, melorin capacity, replace renewals).
"""

import sqlalchemy as sa
from alembic import op

revision = "0048_pasarguard_phase3"
down_revision = "0047_panel_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("sellable", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("servers", sa.Column("sellable_reason", sa.String(300), nullable=True))
    op.add_column("servers", sa.Column("destination_health", sa.JSON(), nullable=True))
    op.add_column("servers", sa.Column("panel_total_users", sa.Integer(), nullable=True))
    op.add_column("servers", sa.Column("capacity_source", sa.String(10), nullable=False, server_default="melorin"))
    op.add_column("servers", sa.Column("capacity_alert_level", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("servers", sa.Column("capacity_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("renewal_mode", sa.String(10), nullable=False, server_default="replace"))
    op.add_column("vpn_accounts", sa.Column("queued_plan", sa.JSON(), nullable=True))
    op.create_table(
        "product_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("panel_id", sa.Uuid(), sa.ForeignKey("panels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("remote_template_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("managed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("panel_id", "product_id", name="uq_product_templates_panel_product"),
    )
    op.create_index("ix_product_templates_panel_id", "product_templates", ["panel_id"])
    op.create_index("ix_product_templates_product_id", "product_templates", ["product_id"])


def downgrade() -> None:
    op.drop_table("product_templates")
    op.drop_column("vpn_accounts", "queued_plan")
    op.drop_column("orders", "renewal_mode")
    for col in (
        "capacity_checked_at",
        "capacity_alert_level",
        "capacity_source",
        "panel_total_users",
        "destination_health",
        "sellable_reason",
        "sellable",
    ):
        op.drop_column("servers", col)
