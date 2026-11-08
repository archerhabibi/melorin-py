"""PasarGuard Phase 6 ("Melorin is a mediator"): configurable retention, orphan handling, issue clean-up.

* ``panels.expected_retention_days``  days the panel must keep expired users when the lifecycle policy is ``aligned`` (decision 2)

Additive and nullable: every existing row keeps today's behaviour (NULL = the renewal grace).
"""

import sqlalchemy as sa
from alembic import op

revision = "0051_pasarguard_phase6"
down_revision = "0050_pasarguard_phase5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("panels", sa.Column("expected_retention_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("panels", "expected_retention_days")
