"""Referral programs are per store: first-touch attribution and the signup-reward guard become unique per (store, customer)."""
import sqlalchemy as sa
from alembic import op

revision = "0033_store_scoped_referral"
down_revision = "0032_bank_sms_auto_verify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Before: one referrer per user for the whole platform, one signup reward per user for the whole platform.
    # After:  one referrer per user per store, one signup reward per user per store. Existing rows stay valid.
    op.drop_constraint("uq_referral_relationships_referred_user_id", "referral_relationships", type_="unique")
    op.create_unique_constraint(
        "uq_referral_relationships_store_id_referred_user_id", "referral_relationships", ["store_id", "referred_user_id"]
    )
    op.drop_constraint("uq_commissions_referred_user_id_kind", "commissions", type_="unique")
    op.create_unique_constraint("uq_commissions_store_id_referred_user_id_kind", "commissions", ["store_id", "referred_user_id", "kind"])


    # One default plan (product_id IS NULL) per store and kind: the old unique constraint never caught NULL duplicates.
    op.execute(
        "DELETE FROM commission_rules r USING commission_rules o "
        "WHERE r.product_id IS NULL AND o.product_id IS NULL AND o.store_id = r.store_id AND o.kind = r.kind "
        "AND (o.updated_at > r.updated_at OR (o.updated_at = r.updated_at AND o.id > r.id))"
    )
    op.create_index(
        "uq_commission_rules_store_kind_default",
        "commission_rules",
        ["store_id", "kind"],
        unique=True,
        postgresql_where=sa.text("product_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_commission_rules_store_kind_default", table_name="commission_rules")
    # The platform-wide rule cannot hold rows made in several stores: keep the oldest per user, drop the rest, then restore it.
    op.execute(
        "DELETE FROM commissions c USING commissions o "
        "WHERE o.referred_user_id = c.referred_user_id AND o.kind = c.kind "
        "AND (o.created_at < c.created_at OR (o.created_at = c.created_at AND o.id < c.id))"
    )
    op.drop_constraint("uq_commissions_store_id_referred_user_id_kind", "commissions", type_="unique")
    op.create_unique_constraint("uq_commissions_referred_user_id_kind", "commissions", ["referred_user_id", "kind"])
    op.execute(
        "DELETE FROM referral_relationships r USING referral_relationships o "
        "WHERE o.referred_user_id = r.referred_user_id "
        "AND (o.created_at < r.created_at OR (o.created_at = r.created_at AND o.id < r.id))"
    )
    op.drop_constraint("uq_referral_relationships_store_id_referred_user_id", "referral_relationships", type_="unique")
    op.create_unique_constraint("uq_referral_relationships_referred_user_id", "referral_relationships", ["referred_user_id"])
