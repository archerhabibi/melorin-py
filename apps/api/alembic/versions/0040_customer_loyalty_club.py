"""Customer loyalty club (docs/22): one club per store with points, tiers, a points ledger, wallet-credit rewards and redemptions.

Six new tables, nothing existing is altered, so the migration is safe on a live database and fully reversible:

* ``loyalty_programs``      the store's earning rules (one row per store, disabled until the owner or Admin turns it on)
* ``loyalty_tiers``         the store's ladder, reached by lifetime EARNED points
* ``loyalty_accounts``      a customer's purse in one store (balance, lifetime earned, points debt after a refund)
* ``loyalty_transactions``  append-only points ledger with an idempotency key
* ``loyalty_rewards``       what points can buy (wallet credit)
* ``loyalty_redemptions``   one reward taken by one customer
"""

import sqlalchemy as sa
from alembic import op

revision = "0040_customer_loyalty_club"
down_revision = "0039_target_selection"
branch_labels = None
depends_on = None


def _ts(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=None if nullable else sa.func.now(), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "loyalty_programs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("earn_unit", sa.BigInteger(), nullable=False),
        sa.Column("points_per_unit", sa.Integer(), nullable=False),
        sa.Column("max_points_per_order", sa.Integer(), nullable=True),
        sa.Column("first_order_bonus", sa.Integer(), nullable=False),
        sa.Column("referral_bonus", sa.Integer(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_loyalty_programs"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_loyalty_programs_store_id_stores"),
        sa.UniqueConstraint("store_id", name="uq_loyalty_programs_store_id"),
    )
    op.create_index("ix_loyalty_programs_store_id", "loyalty_programs", ["store_id"])

    op.create_table(
        "loyalty_tiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("min_points", sa.Integer(), nullable=False),
        sa.Column("multiplier_bp", sa.Integer(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_loyalty_tiers"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_loyalty_tiers_store_id_stores"),
        sa.UniqueConstraint("store_id", "min_points", name="uq_loyalty_tiers_store_id_min_points"),
    )
    op.create_index("ix_loyalty_tiers_store_id", "loyalty_tiers", ["store_id"])

    op.create_table(
        "loyalty_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False),
        sa.Column("lifetime_earned", sa.BigInteger(), nullable=False),
        sa.Column("debt", sa.BigInteger(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_loyalty_accounts"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_loyalty_accounts_store_id_stores"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_loyalty_accounts_user_id_users"),
        sa.UniqueConstraint("store_id", "user_id", name="uq_loyalty_accounts_store_id_user_id"),
        sa.CheckConstraint("balance >= 0 AND debt >= 0", name="ck_loyalty_accounts_non_negative"),
    )
    op.create_index("ix_loyalty_accounts_store_id", "loyalty_accounts", ["store_id"])
    op.create_index("ix_loyalty_accounts_user_id", "loyalty_accounts", ["user_id"])

    op.create_table(
        "loyalty_rewards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("cost_points", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("per_user_limit", sa.Integer(), nullable=True),
        sa.Column("redeemed_count", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_loyalty_rewards"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_loyalty_rewards_store_id_stores"),
    )
    op.create_index("ix_loyalty_rewards_store_id", "loyalty_rewards", ["store_id"])

    op.create_table(
        "loyalty_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("reward_id", sa.Uuid(), nullable=True),
        sa.Column("reverses_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("memo", sa.String(length=255), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("debt_recovered", sa.BigInteger(), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_loyalty_transactions"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_loyalty_transactions_store_id_stores"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_loyalty_transactions_user_id_users"),
        sa.ForeignKeyConstraint(["account_id"], ["loyalty_accounts.id"], name="fk_loyalty_transactions_account_id_loyalty_accounts"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_loyalty_transactions_order_id_orders"),
        sa.ForeignKeyConstraint(["reward_id"], ["loyalty_rewards.id"], name="fk_loyalty_transactions_reward_id_loyalty_rewards"),
        sa.ForeignKeyConstraint(
            ["reverses_id"], ["loyalty_transactions.id"], name="fk_loyalty_transactions_reverses_id_loyalty_transactions"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_loyalty_transactions_idempotency_key"),
    )
    op.create_index("ix_loyalty_transactions_store_id", "loyalty_transactions", ["store_id"])
    op.create_index("ix_loyalty_transactions_user_id", "loyalty_transactions", ["user_id"])
    op.create_index("ix_loyalty_transactions_account_id", "loyalty_transactions", ["account_id"])
    op.create_index("ix_loyalty_transactions_order_id", "loyalty_transactions", ["order_id"])
    op.create_index("ix_loyalty_transactions_store_user_created", "loyalty_transactions", ["store_id", "user_id", "created_at"])

    op.create_table(
        "loyalty_redemptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("reward_id", sa.Uuid(), nullable=False),
        sa.Column("points_spent", sa.Integer(), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("ledger_tx_id", sa.Uuid(), nullable=True),
        sa.Column("points_tx_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_loyalty_redemptions"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_loyalty_redemptions_store_id_stores"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_loyalty_redemptions_user_id_users"),
        sa.ForeignKeyConstraint(["reward_id"], ["loyalty_rewards.id"], name="fk_loyalty_redemptions_reward_id_loyalty_rewards"),
        sa.UniqueConstraint("store_id", "user_id", "idempotency_key", name="uq_loyalty_redemptions_store_id_user_id_idempotency_key"),
    )
    op.create_index("ix_loyalty_redemptions_store_id", "loyalty_redemptions", ["store_id"])
    op.create_index("ix_loyalty_redemptions_user_id", "loyalty_redemptions", ["user_id"])
    op.create_index("ix_loyalty_redemptions_reward_id", "loyalty_redemptions", ["reward_id"])


def downgrade() -> None:
    for table in (
        "loyalty_redemptions",
        "loyalty_transactions",
        "loyalty_rewards",
        "loyalty_accounts",
        "loyalty_tiers",
        "loyalty_programs",
    ):
        op.drop_table(table)
