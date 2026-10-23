"""Telegram Event Center: connection-health columns on telegram_event_destinations."""
from alembic import op
import sqlalchemy as sa

revision = "0031_event_center_health"
down_revision = "0030_broadcasts"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("telegram_event_destinations") as batch:
        batch.add_column(sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_error", sa.String(300), nullable=True))
        batch.add_column(sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("telegram_event_destinations") as batch:
        batch.drop_column("last_error_at")
        batch.drop_column("last_error")
        batch.drop_column("last_sent_at")
