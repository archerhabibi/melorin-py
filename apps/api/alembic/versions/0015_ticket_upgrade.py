"""0015 – Ticket desk upgrade: priority, internal staff notes and message editing.

Changes
-------
* ``tickets.priority``            VARCHAR(10) NOT NULL DEFAULT 'normal' (+ index)
* ``ticket_messages.is_internal`` BOOLEAN NOT NULL DEFAULT false (staff-only notes)
* ``ticket_messages.edited_at``   TIMESTAMPTZ NULL (set when an author edits a message)
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_ticket_upgrade"
down_revision = "0014_short_codes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tickets", sa.Column("priority", sa.String(10), nullable=False, server_default="normal"))
    op.create_index("ix_tickets_priority", "tickets", ["priority"])
    op.add_column("ticket_messages", sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("ticket_messages", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("ticket_messages", "edited_at")
    op.drop_column("ticket_messages", "is_internal")
    op.drop_index("ix_tickets_priority", table_name="tickets")
    op.drop_column("tickets", "priority")
