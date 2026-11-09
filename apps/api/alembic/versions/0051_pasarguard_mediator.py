"""PasarGuard mediator rework: configurable retention days for the ``aligned`` lifecycle policy (decision 2).

* ``panels.expected_retention_days``  nullable; ``NULL`` keeps today's behaviour (Melorin's renewal grace, 10 days)

Additive: no existing row changes meaning. (``panel_orphans.status`` is a free string; ``manual`` needs no schema change.)
"""

import sqlalchemy as sa
from alembic import op

revision = "0051_pasarguard_mediator"
down_revision = "0050_pasarguard_phase5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("panels", sa.Column("expected_retention_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("panels", "expected_retention_days")
