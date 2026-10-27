"""Only the sign-up reward is unique per (store, referred customer); the purchase commission is paid on every order.

0036 (and the platform-wide rule before it) made ``(referred_user_id, kind)`` unique for BOTH kinds, so a customer could produce a
single ``commission`` row per store and every later order failed in the worker with a unique violation - the referrer was never
paid again. The guard is now a partial unique index on ``kind = 'signup_reward'`` only. ``(order_id, kind)`` stays unique, so one
order still pays at most once per kind.
"""

import sqlalchemy as sa
from alembic import op

revision = "0037_commission_reward_unique"
down_revision = "0036_store_scoped_referral"
branch_labels = None
depends_on = None

_OLD = "uq_commissions_store_id_referred_user_id_kind"
_NEW = "uq_commissions_store_referred_signup_reward"


def upgrade() -> None:
    # Safe on live data: the old constraint allowed at most one row per (store, customer, kind), so no existing row violates the new one.
    op.drop_constraint(_OLD, "commissions", type_="unique")
    op.create_index(
        _NEW,
        "commissions",
        ["store_id", "referred_user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'signup_reward'"),
        sqlite_where=sa.text("kind = 'signup_reward'"),
    )


def downgrade() -> None:
    # Money rows are never deleted by a downgrade: if a customer already has several commissions this fails loudly, and the
    # operator decides what to do with them instead of silently losing paid commissions.
    op.drop_index(_NEW, table_name="commissions")
    op.create_unique_constraint(_OLD, "commissions", ["store_id", "referred_user_id", "kind"])
