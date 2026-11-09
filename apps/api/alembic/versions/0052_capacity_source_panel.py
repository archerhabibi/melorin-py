"""Decision 6 (8 Nov 2026): the panel is the capacity truth.

New destinations default to ``capacity_source = 'panel'`` and existing ones follow. Safe: ``effective_load`` falls back to
Melorin's own count whenever the panel's figure has not been read yet, and it never lowers the load below Melorin's count.
"""

import sqlalchemy as sa
from alembic import op

revision = "0052_capacity_source_panel"
down_revision = "0051_pasarguard_mediator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("servers") as batch:
        batch.alter_column("capacity_source", existing_type=sa.String(10), server_default="panel", existing_nullable=False)
    op.execute("UPDATE servers SET capacity_source = 'panel' WHERE capacity_source = 'melorin'")


def downgrade() -> None:
    with op.batch_alter_table("servers") as batch:
        batch.alter_column("capacity_source", existing_type=sa.String(10), server_default="melorin", existing_nullable=False)
