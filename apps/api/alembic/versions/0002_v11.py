"""Melorin v1.1: wallet-first, store-scoped payments, coupons, commissions, API and webhooks.

This migration is deliberately explicit for databases created by 0001_initial. Fresh installs
still use the complete metadata from 0001; this revision is for existing deployments.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_v11"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _has(table, column):
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table, column, type_, *, nullable=True, default=None):
    if _has(table, column):
        return
    args = [sa.Column(column, type_, nullable=nullable)]
    if default is not None:
        args[0].server_default = sa.text(default)
    op.add_column(table, args[0])


def upgrade():
    # 0001 is the frozen full-schema baseline. On a fresh install it already
    # contains the v1.1 objects, so this compatibility revision is a no-op.
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if {"coupon_redemptions", "store_payment_configurations", "commission_rules", "commission_clawbacks", "identity_link_reviews", "webhook_endpoints", "webhook_deliveries"} <= tables:
        return
    # Wallet identity now includes kind + currency. Legacy rows are preserved
    # as IRR; newly created stores/wallets use the application default IRT.
    _add("wallets", "kind", sa.String(20), nullable=False, default="'customer'")
    _add("wallets", "currency", sa.String(8), nullable=False, default="'IRT'")
    try:
        op.drop_constraint("uq_wallets_user_id_store_id", "wallets", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint("uq_wallets_user_store_kind_currency", "wallets", ["user_id", "store_id", "kind", "currency"])

    # Coupon columns and a redemption ledger.
    for name, typ, default in (
        ("owner_key", sa.String(64), "''"), ("scope", sa.String(10), "'store'"),
        ("allowed_store_ids", sa.JSON(), None), ("allowed_store_kinds", sa.JSON(), None), ("product_ids", sa.JSON(), None),
        ("creator_type", sa.String(10), "'admin'"), ("creator_id", postgresql.UUID(as_uuid=True), None),
        ("funded_by", sa.String(10), "'store'"), ("percent_bp", sa.Integer(), "0"), ("max_discount", sa.BigInteger(), None),
        ("min_amount", sa.BigInteger(), "0"), ("currency", sa.String(8), None), ("starts_at", sa.DateTime(timezone=True), None),
        ("ends_at", sa.DateTime(timezone=True), None), ("per_customer_limit", sa.Integer(), "1"),
        ("combinable", sa.Boolean(), "false"), ("status", sa.String(20), "'active'"),
    ):
        _add("coupons", name, typ, nullable=True if default is None else False, default=default)
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE coupons SET owner_key = COALESCE(owner_key, store_id::text), percent_bp = COALESCE(percent_bp, percent * 100), max_discount = COALESCE(max_discount, max_amount), starts_at = COALESCE(starts_at, created_at), ends_at = valid_until, status = CASE WHEN is_active THEN 'active' ELSE 'disabled' END WHERE owner_key IS NULL OR owner_key = ''"))
    try:
        op.drop_constraint("uq_coupons_store_id_code", "coupons", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint("uq_coupons_owner_key_code", "coupons", ["owner_key", "code"])
    _add("coupon_redemptions", "_placeholder", sa.Integer()) if False else None
    op.create_table(
        "coupon_redemptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("coupon_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("coupons.id"), nullable=False), sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False), sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False), sa.Column("currency", sa.String(8), nullable=False), sa.Column("status", sa.String(20), server_default="'applied'", nullable=False),
        sa.UniqueConstraint("coupon_id", "order_id"),
    )

    # Store-scoped payment destinations.
    op.create_table(
        "store_payment_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False), sa.Column("provider", sa.String(30), nullable=False), sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False), sa.Column("public_config", sa.JSON()), sa.Column("secret_enc", sa.Text()), sa.Column("updated_by", postgresql.UUID(as_uuid=True)), sa.UniqueConstraint("store_id", "provider"),
    )

    # API credential lifecycle/rate limiting.
    _add("api_credentials", "updated_at", sa.DateTime(timezone=True), nullable=True, default="CURRENT_TIMESTAMP")
    for name, typ, default in (("rate_limit_per_minute", sa.Integer(), "120"), ("ip_allowlist", sa.JSON(), None), ("created_by", postgresql.UUID(as_uuid=True), None), ("rotated_from_id", postgresql.UUID(as_uuid=True), None), ("revoked_at", sa.DateTime(timezone=True), None), ("expires_at", sa.DateTime(timezone=True), None)):
        _add("api_credentials", name, typ, nullable=True if default is None else False, default=default)

    # First-touch attribution and configurable reward rules.
    try:
        op.drop_constraint("uq_referral_relationships_store_id_referred_user_id", "referral_relationships", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint("uq_referral_relationships_referred_user_id", "referral_relationships", ["referred_user_id"])
    _add("commissions", "reversed_amount", sa.BigInteger(), nullable=False, default="0")
    _add("commissions", "offset_amount", sa.BigInteger(), nullable=False, default="0")
    _add("commissions", "currency", sa.String(8), nullable=True)
    op.create_table(
        "commission_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False), sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id")), sa.Column("kind", sa.String(20), nullable=False), sa.Column("model", sa.String(10), nullable=False), sa.Column("value", sa.BigInteger(), nullable=False), sa.Column("max_amount", sa.BigInteger()), sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False), sa.UniqueConstraint("store_id", "product_id", "kind"),
    )
    op.create_table(
        "commission_clawbacks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("referrer_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False), sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False), sa.Column("currency", sa.String(8), nullable=False), sa.Column("outstanding", sa.BigInteger(), server_default="0", nullable=False), sa.UniqueConstraint("referrer_user_id", "store_id", "currency"),
    )

    op.create_table(
        "identity_link_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False), sa.Column("source_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False), sa.Column("candidate_user_ids", sa.JSON(), nullable=False), sa.Column("provider", sa.String(20), nullable=False), sa.Column("reason", sa.String(200), nullable=False), sa.Column("status", sa.String(20), server_default="'open'", nullable=False), sa.Column("resolved_by", postgresql.UUID(as_uuid=True)), sa.Column("resolution_note", sa.String(500)),
    )

    # Outgoing webhook endpoint and delivery log.
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False), sa.Column("url", sa.String(500), nullable=False), sa.Column("description", sa.String(200)), sa.Column("events", sa.JSON(), server_default="'[]'", nullable=False), sa.Column("secret_enc", sa.Text(), nullable=False), sa.Column("previous_secret_enc", sa.Text()), sa.Column("previous_secret_expires_at", sa.DateTime(timezone=True)), sa.Column("status", sa.String(20), server_default="'active'", nullable=False), sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False), sa.Column("created_by", postgresql.UUID(as_uuid=True)),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("endpoint_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("webhook_endpoints.id"), nullable=False), sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("event_id", sa.String(64), nullable=False), sa.Column("event_type", sa.String(60), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("status", sa.String(20), server_default="'pending'", nullable=False), sa.Column("attempts", sa.Integer(), server_default="0", nullable=False), sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("last_status_code", sa.Integer()), sa.Column("last_error", sa.Text()), sa.Column("last_response_ms", sa.Integer()), sa.Column("delivered_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("endpoint_id", "event_id"),
    )


def downgrade():
    # Preserve financial/audit data. Rolling back feature tables is unsafe; downgrade is intentionally blocked.
    raise RuntimeError("Melorin v1.1 downgrade is intentionally blocked; restore a database backup instead.")
