"""PasarGuard roadmap Phase 1 (PG-01 / PG-02 / PG-04 / PG-06): real health, full status sync, issue handling, notice fixes.

* ``panels.health_detail``                     node-level health summary (JSON); ``health_status`` gains ``degraded``
* ``panel_nodes``                              last known state of every panel node
* ``vpn_accounts``                             ``last_synced_at`` / ``remote_status`` / ``online_at`` / ``lifetime_used_traffic`` /
                                               ``sync_error_count`` (panel is the source of truth) and ``traffic_notified_level``
* ``reconciliation_issues``                    ``occurrences`` / ``last_seen_at`` / ``resolved_at`` / ``resolution`` and a PARTIAL UNIQUE
                                               index: one OPEN issue per (account, kind). Existing open duplicates are folded first
                                               (oldest kept, ``occurrences`` summed, the rest ``resolved`` with resolution='duplicate').
* ``panel_orphans``                            panel users Melorin does not know (never deleted automatically)

Additive and nullable/defaulted: nothing existing changes behaviour until the new code runs.
"""

import sqlalchemy as sa
from alembic import op

revision = "0045_panel_ops_phase1"
down_revision = "0044_panel_capabilities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("panels", sa.Column("health_detail", sa.JSON(), nullable=True))

    op.add_column("vpn_accounts", sa.Column("traffic_notified_level", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("vpn_accounts", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("vpn_accounts", sa.Column("remote_status", sa.String(20), nullable=True))
    op.add_column("vpn_accounts", sa.Column("online_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("vpn_accounts", sa.Column("lifetime_used_traffic", sa.BigInteger(), nullable=True))
    op.add_column("vpn_accounts", sa.Column("sync_error_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_vpn_accounts_last_synced_at", "vpn_accounts", ["last_synced_at"])

    op.add_column("reconciliation_issues", sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("reconciliation_issues", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reconciliation_issues", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reconciliation_issues", sa.Column("resolution", sa.String(300), nullable=True))
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE reconciliation_issues SET last_seen_at = created_at WHERE last_seen_at IS NULL"))
    rows = bind.execute(
        sa.text("SELECT id, vpn_account_id, kind FROM reconciliation_issues WHERE status = 'open' ORDER BY created_at ASC, id ASC")
    ).fetchall()
    keeper: dict[tuple, object] = {}
    folded: dict[object, int] = {}
    for issue_id, account_id, kind in rows:
        key = (account_id, kind)
        if key not in keeper:
            keeper[key] = issue_id
            continue
        folded[keeper[key]] = folded.get(keeper[key], 0) + 1
        bind.execute(
            sa.text(
                "UPDATE reconciliation_issues SET status = 'resolved', resolution = 'duplicate', resolved_at = CURRENT_TIMESTAMP WHERE id = :id"
            ),
            {"id": issue_id},
        )
    for issue_id, extra in folded.items():
        bind.execute(
            sa.text("UPDATE reconciliation_issues SET occurrences = occurrences + :n WHERE id = :id"), {"n": extra, "id": issue_id}
        )
    op.create_index(
        "uq_reconciliation_issue_open",
        "reconciliation_issues",
        ["vpn_account_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
        sqlite_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "panel_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("panel_id", sa.Uuid(), sa.ForeignKey("panels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("remote_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("xray_version", sa.String(40), nullable=True),
        sa.Column("usage_coefficient", sa.Float(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("panel_id", "remote_id", name="uq_panel_nodes_panel_remote"),
    )
    op.create_index("ix_panel_nodes_panel_id", "panel_nodes", ["panel_id"])
    op.create_index("ix_panel_nodes_status", "panel_nodes", ["status"])

    op.create_table(
        "panel_orphans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("panel_id", sa.Uuid(), sa.ForeignKey("panels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("remote_id", sa.Integer(), nullable=True),
        sa.Column("remote_status", sa.String(20), nullable=True),
        sa.Column("owner_username", sa.String(64), nullable=True),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("traffic_limit_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("traffic_used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("panel_id", "username", name="uq_panel_orphans_panel_username"),
    )
    op.create_index("ix_panel_orphans_panel_id", "panel_orphans", ["panel_id"])
    op.create_index("ix_panel_orphans_status", "panel_orphans", ["status"])


def downgrade() -> None:
    op.drop_table("panel_orphans")
    op.drop_table("panel_nodes")
    op.drop_index("uq_reconciliation_issue_open", table_name="reconciliation_issues")
    for col in ("resolution", "resolved_at", "last_seen_at", "occurrences"):
        op.drop_column("reconciliation_issues", col)
    op.drop_index("ix_vpn_accounts_last_synced_at", table_name="vpn_accounts")
    for col in ("sync_error_count", "lifetime_used_traffic", "online_at", "remote_status", "last_synced_at", "traffic_notified_level"):
        op.drop_column("vpn_accounts", col)
    op.drop_column("panels", "health_detail")
