"""Prevent duplicate first-order referral rewards."""
from alembic import op
import sqlalchemy as sa

revision = "0009_referral_first_reward_guard"
down_revision = "0008_bot_store_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("commissions", sa.Column("referred_user_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE commissions c SET referred_user_id = o.user_id "
            "FROM orders o WHERE c.order_id = o.id AND c.referred_user_id IS NULL"
        )
    )
    op.alter_column("commissions", "referred_user_id", nullable=False)
    op.execute(
        sa.text(
            "DELETE FROM commissions c USING commissions newer "
            "WHERE c.kind = 'signup_reward' AND newer.kind = c.kind "
            "AND newer.referred_user_id = c.referred_user_id "
            "AND newer.created_at < c.created_at"
        )
    )
    op.create_foreign_key(
        "fk_commissions_referred_user_id_users",
        "commissions",
        "users",
        ["referred_user_id"],
        ["id"],
    )
    op.create_index("ix_commissions_referred_user_id", "commissions", ["referred_user_id"])
    op.create_unique_constraint(
        "uq_commissions_referred_user_id_kind",
        "commissions",
        ["referred_user_id", "kind"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_commissions_referred_user_id_kind", "commissions", type_="unique")
    op.drop_index("ix_commissions_referred_user_id", table_name="commissions")
    op.drop_constraint("fk_commissions_referred_user_id_users", "commissions", type_="foreignkey")
    op.drop_column("commissions", "referred_user_id")
