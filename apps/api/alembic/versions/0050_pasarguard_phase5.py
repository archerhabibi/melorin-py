"""PasarGuard roadmap Phase 5 (PG-14 metrics, PG-15 settings drift, PG-16 panel backup).

* ``panels.metrics_snapshot`` / ``metrics_snapshot_at``  last live reading of a panel, rendered at /metrics scrape time
* ``panels.expired_cleanup_policy`` / ``settings_drift`` / ``settings_drift_at``  lifecycle policy and the last drift verdict
* ``backup_runs.target``  ``melorin`` (existing rows) or ``panel``

Additive and defaulted: every existing row keeps today's behaviour (policy ``keep`` = the safe reading of "panel auto-delete stays off").
"""

import sqlalchemy as sa
from alembic import op

revision = "0050_pasarguard_phase5"
down_revision = "0049_pasarguard_phase4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("panels", sa.Column("metrics_snapshot", sa.JSON(), nullable=True))
    op.add_column("panels", sa.Column("metrics_snapshot_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("panels", sa.Column("expired_cleanup_policy", sa.String(10), nullable=False, server_default="keep"))
    op.add_column("panels", sa.Column("settings_drift", sa.JSON(), nullable=True))
    op.add_column("panels", sa.Column("settings_drift_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("backup_runs", sa.Column("target", sa.String(12), nullable=False, server_default="melorin"))
    op.create_index("ix_backup_runs_target", "backup_runs", ["target"])


def downgrade() -> None:
    op.drop_index("ix_backup_runs_target", table_name="backup_runs")
    op.drop_column("backup_runs", "target")
    for col in ("settings_drift_at", "settings_drift", "expired_cleanup_policy", "metrics_snapshot_at", "metrics_snapshot"):
        op.drop_column("panels", col)
