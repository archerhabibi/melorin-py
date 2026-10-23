"""Admin manual tasks: the checklist of steps an admin must do by hand when a reseller registers (Google / Telegram / DNS)."""
from alembic import op
import sqlalchemy as sa

revision = "0028_admin_manual_tasks"
down_revision = "0027_channel_binding"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("done_by", sa.Uuid(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_admin_tasks"),
        sa.ForeignKeyConstraint(["application_id"], ["reseller_applications.id"], name="fk_admin_tasks_application_id_reseller_applications"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_admin_tasks_store_id_stores"),
        sa.ForeignKeyConstraint(["done_by"], ["users.id"], name="fk_admin_tasks_done_by_users"),
        sa.UniqueConstraint("kind", "application_id", name="uq_admin_tasks_kind_application"),
    )
    op.create_index("ix_admin_tasks_kind", "admin_tasks", ["kind"])
    op.create_index("ix_admin_tasks_application_id", "admin_tasks", ["application_id"])
    op.create_index("ix_admin_tasks_status", "admin_tasks", ["status"])


def downgrade():
    op.drop_index("ix_admin_tasks_status", table_name="admin_tasks")
    op.drop_index("ix_admin_tasks_application_id", table_name="admin_tasks")
    op.drop_index("ix_admin_tasks_kind", table_name="admin_tasks")
    op.drop_table("admin_tasks")
