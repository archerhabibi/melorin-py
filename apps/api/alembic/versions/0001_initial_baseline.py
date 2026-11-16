"""Melorin initial baseline (docs/19-DATABASE-MIGRATIONS.md).

The project is unreleased, so the former 0001..0057 chain was replaced by this single revision. It creates the complete
current schema on an EMPTY database:

* every table, index and constraint declared by ``melorin.models`` (generated from the metadata, then verified by
  ``tests/integration/test_migration_baseline.py`` which diffs the migrated database against the models);
* PostgreSQL sequences ``order_number_seq`` / ``ticket_number_seq`` (short customer-facing codes);
* the append-only guard on ``account_link_audits`` (trigger on PostgreSQL, triggers on SQLite);
* the two idempotent default rows of ``system_settings`` (provisioning retry policy).

Downgrade drops everything this revision created; it is intended for development databases only.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_baseline"
down_revision = None
branch_labels = None
depends_on = None

_APPEND_ONLY_TABLES = ("account_link_audits",)
_SEQUENCES = ("order_number_seq", "ticket_number_seq")
_SETTINGS = (
    ("provisioning.max_attempts", 4),
    ("provisioning.backoff_seconds", [5, 7, 10]),
)


def _append_only(table: str) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            f"CREATE FUNCTION {table}_append_only() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION '{table} is append-only'; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_append_only()"
        )
    elif dialect == "sqlite":
        for verb in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
            )


def _drop_append_only(table: str) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_change ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {table}_append_only()")
    elif dialect == "sqlite":
        for verb in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_{verb}")


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for seq in _SEQUENCES:
            op.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq} START 1")
    op.create_table(
        "audit_events",
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_action"), "audit_events", ["action"], unique=False)
    op.create_index(op.f("ix_audit_events_actor_id"), "audit_events", ["actor_id"], unique=False)
    op.create_index(op.f("ix_audit_events_entity_id"), "audit_events", ["entity_id"], unique=False)
    op.create_index(op.f("ix_audit_events_store_id"), "audit_events", ["store_id"], unique=False)
    op.create_table(
        "backup_runs",
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("target", sa.String(length=12), server_default="melorin", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_runs")),
    )
    op.create_index(op.f("ix_backup_runs_target"), "backup_runs", ["target"], unique=False)
    op.create_table(
        "bundles",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("selection_mode", sa.String(length=20), nullable=False),
        sa.Column("balancing", sa.String(length=20), server_default="round_robin", nullable=False),
        sa.Column("naming_mode", sa.String(length=20), nullable=False),
        sa.Column("kind_label", sa.String(length=40), server_default="", nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("reseller_enabled", sa.Boolean(), nullable=False),
        sa.Column("sales_limit", sa.Integer(), nullable=True),
        sa.Column("sold_count", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bundles")),
    )
    op.create_table(
        "feature_flags",
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feature_flags")),
        sa.UniqueConstraint("key", "scope_type", "scope_id", name=op.f("uq_feature_flags_key_scope_type_scope_id")),
    )
    op.create_table(
        "outbox_events",
        sa.Column("topic", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dedup_key", sa.String(length=200), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
        sa.UniqueConstraint("dedup_key", name=op.f("uq_outbox_events_dedup_key")),
    )
    op.create_index(op.f("ix_outbox_events_available_at"), "outbox_events", ["available_at"], unique=False)
    op.create_index(op.f("ix_outbox_events_status"), "outbox_events", ["status"], unique=False)
    op.create_index(op.f("ix_outbox_events_topic"), "outbox_events", ["topic"], unique=False)
    op.create_table(
        "panels",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("base_url", sa.String(length=300), nullable=False),
        sa.Column("credentials_enc", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("health_status", sa.String(length=20), nullable=False),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_error", sa.Text(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("capabilities_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_detail", sa.JSON(), nullable=True),
        sa.Column("webhook_secret_enc", sa.Text(), nullable=True),
        sa.Column("webhook_last_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subscription_check", sa.JSON(), nullable=True),
        sa.Column("subscription_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=True),
        sa.Column("metrics_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_cleanup_policy", sa.String(length=10), server_default="keep", nullable=False),
        sa.Column("expected_retention_days", sa.Integer(), nullable=True),
        sa.Column("settings_drift", sa.JSON(), nullable=True),
        sa.Column("settings_drift_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_panels")),
    )
    op.create_table(
        "persons",
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("central_user_id", sa.Uuid(), nullable=True),
        sa.Column("merged_into_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merged_into_id"], ["persons.id"], name=op.f("fk_persons_merged_into_id_persons")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_persons")),
        sa.UniqueConstraint("public_id", name=op.f("uq_persons_public_id")),
    )
    op.create_index(op.f("ix_persons_status"), "persons", ["status"], unique=False)
    op.create_table(
        "security_events",
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_events")),
    )
    op.create_index(op.f("ix_security_events_kind"), "security_events", ["kind"], unique=False)
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_settings")),
        sa.UniqueConstraint("key", name=op.f("uq_system_settings_key")),
    )
    op.create_table(
        "account_link_audits",
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(length=12), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name=op.f("fk_account_link_audits_person_id_persons")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_link_audits")),
    )
    op.create_index(op.f("ix_account_link_audits_action"), "account_link_audits", ["action"], unique=False)
    op.create_index(op.f("ix_account_link_audits_operation_id"), "account_link_audits", ["operation_id"], unique=False)
    op.create_index(op.f("ix_account_link_audits_person_id"), "account_link_audits", ["person_id"], unique=False)
    op.create_table(
        "bundle_members",
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("panel_id", sa.Uuid(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("sales_limit", sa.Integer(), nullable=True),
        sa.Column("sold_count", sa.Integer(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"], name=op.f("fk_bundle_members_bundle_id_bundles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], name=op.f("fk_bundle_members_panel_id_panels")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bundle_members")),
        sa.UniqueConstraint("bundle_id", "panel_id", name=op.f("uq_bundle_members_bundle_id_panel_id")),
    )
    op.create_index(op.f("ix_bundle_members_bundle_id"), "bundle_members", ["bundle_id"], unique=False)
    op.create_index(op.f("ix_bundle_members_panel_id"), "bundle_members", ["panel_id"], unique=False)
    op.create_table(
        "panel_nodes",
        sa.Column("panel_id", sa.Uuid(), nullable=False),
        sa.Column("remote_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("xray_version", sa.String(length=40), nullable=True),
        sa.Column("usage_coefficient", sa.Float(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], name=op.f("fk_panel_nodes_panel_id_panels"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_panel_nodes")),
        sa.UniqueConstraint("panel_id", "remote_id", name="uq_panel_nodes_panel_remote"),
    )
    op.create_index(op.f("ix_panel_nodes_panel_id"), "panel_nodes", ["panel_id"], unique=False)
    op.create_index(op.f("ix_panel_nodes_status"), "panel_nodes", ["status"], unique=False)
    op.create_table(
        "panel_orphans",
        sa.Column("panel_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("remote_id", sa.Integer(), nullable=True),
        sa.Column("owner_username", sa.String(length=64), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], name=op.f("fk_panel_orphans_panel_id_panels"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_panel_orphans")),
        sa.UniqueConstraint("panel_id", "username", name="uq_panel_orphans_panel_username"),
    )
    op.create_index(op.f("ix_panel_orphans_panel_id"), "panel_orphans", ["panel_id"], unique=False)
    op.create_index(op.f("ix_panel_orphans_status"), "panel_orphans", ["status"], unique=False)
    op.create_table(
        "products",
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("traffic_gb", sa.Integer(), nullable=False),
        sa.Column("max_devices", sa.Integer(), nullable=True),
        sa.Column("specs", sa.JSON(), nullable=True),
        sa.Column("main_price", sa.BigInteger(), nullable=False),
        sa.Column("reseller_price", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("reseller_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("default_bundle_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["default_bundle_id"], ["bundles.id"], name=op.f("fk_products_default_bundle_id_bundles"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("code", name=op.f("uq_products_code")),
    )
    op.create_index(op.f("ix_products_category"), "products", ["category"], unique=False)
    op.create_index(op.f("ix_products_default_bundle_id"), "products", ["default_bundle_id"], unique=False)
    op.create_table(
        "servers",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("panel_id", sa.Uuid(), nullable=False),
        sa.Column("location", sa.String(length=100), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("allow_test", sa.Boolean(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("target", sa.JSON(), nullable=True),
        sa.Column("last_assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sellable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sellable_reason", sa.String(length=300), nullable=True),
        sa.Column("destination_health", sa.JSON(), nullable=True),
        sa.Column("capacity_source", sa.String(length=10), server_default="panel", nullable=False),
        sa.Column("capacity_alert_level", sa.Integer(), server_default="0", nullable=False),
        sa.Column("capacity_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], name=op.f("fk_servers_panel_id_panels")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_servers")),
    )
    op.create_index(op.f("ix_servers_panel_id"), "servers", ["panel_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("is_super_admin", sa.Boolean(), nullable=False),
        sa.Column("admin_roles", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_guest", sa.Boolean(), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("referral_code", sa.String(length=16), nullable=False),
        sa.Column("totp_secret_enc", sa.String(length=500), nullable=True),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False),
        sa.Column("totp_last_counter", sa.Integer(), nullable=True),
        sa.Column("allowed_ips", sa.JSON(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name=op.f("fk_users_person_id_persons")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("referral_code", name=op.f("uq_users_referral_code")),
    )
    op.create_index(op.f("ix_users_person_id"), "users", ["person_id"], unique=False)
    op.create_table(
        "account_consolidation_operations",
        sa.Column("target_person_id", sa.Uuid(), nullable=False),
        sa.Column("central_user_id", sa.Uuid(), nullable=False),
        sa.Column("source_user_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("initiated_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("preflight", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], name=op.f("fk_account_consolidation_operations_approved_by_users")),
        sa.ForeignKeyConstraint(["central_user_id"], ["users.id"], name=op.f("fk_account_consolidation_operations_central_user_id_users")),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"], name=op.f("fk_account_consolidation_operations_initiated_by_users")),
        sa.ForeignKeyConstraint(
            ["target_person_id"], ["persons.id"], name=op.f("fk_account_consolidation_operations_target_person_id_persons")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_consolidation_operations")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_account_consolidation_operations_idempotency_key")),
    )
    op.create_index(op.f("ix_account_consolidation_operations_status"), "account_consolidation_operations", ["status"], unique=False)
    op.create_index(
        op.f("ix_account_consolidation_operations_target_person_id"), "account_consolidation_operations", ["target_person_id"], unique=False
    )
    op.create_table(
        "admin_invites",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_admin_invites_created_by_users")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_admin_invites_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_admin_invites_token_hash")),
    )
    op.create_index(op.f("ix_admin_invites_expires_at"), "admin_invites", ["expires_at"], unique=False)
    op.create_index(op.f("ix_admin_invites_user_id"), "admin_invites", ["user_id"], unique=False)
    op.create_table(
        "bundle_products",
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("main_price", sa.BigInteger(), nullable=True),
        sa.Column("reseller_price", sa.BigInteger(), nullable=True),
        sa.Column("is_listed", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"], name=op.f("fk_bundle_products_bundle_id_bundles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_bundle_products_product_id_products"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bundle_products")),
        sa.UniqueConstraint("bundle_id", "product_id", name=op.f("uq_bundle_products_bundle_id_product_id")),
    )
    op.create_index(op.f("ix_bundle_products_bundle_id"), "bundle_products", ["bundle_id"], unique=False)
    op.create_index(op.f("ix_bundle_products_product_id"), "bundle_products", ["product_id"], unique=False)
    op.create_table(
        "identities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=320), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name=op.f("fk_identities_person_id_persons")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_identities_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identities")),
        sa.UniqueConstraint("provider", "subject", name=op.f("uq_identities_provider_subject")),
    )
    op.create_index(op.f("ix_identities_person_id"), "identities", ["person_id"], unique=False)
    op.create_index(op.f("ix_identities_user_id"), "identities", ["user_id"], unique=False)
    op.create_index(
        "uq_identities_one_active_telegram_per_person",
        "identities",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("provider = 'telegram' AND status = 'active'"),
        sqlite_where=sa.text("provider = 'telegram' AND status = 'active'"),
    )
    op.create_table(
        "identity_link_reviews",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("source_user_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_user_ids", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolution_note", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_user_id"], ["users.id"], name=op.f("fk_identity_link_reviews_source_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_link_reviews")),
    )
    op.create_index(op.f("ix_identity_link_reviews_email"), "identity_link_reviews", ["email"], unique=False)
    op.create_index(op.f("ix_identity_link_reviews_status"), "identity_link_reviews", ["status"], unique=False)
    op.create_table(
        "product_templates",
        sa.Column("panel_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("remote_template_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("managed", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], name=op.f("fk_product_templates_panel_id_panels"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_product_templates_product_id_products"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_templates")),
        sa.UniqueConstraint("panel_id", "product_id", name="uq_product_templates_panel_product"),
    )
    op.create_index(op.f("ix_product_templates_panel_id"), "product_templates", ["panel_id"], unique=False)
    op.create_index(op.f("ix_product_templates_product_id"), "product_templates", ["product_id"], unique=False)
    op.create_table(
        "stores",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("parent_store_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("branding", sa.JSON(), nullable=True),
        sa.Column("bot_messages", sa.JSON(), nullable=True),
        sa.Column("bot_token_enc", sa.String(length=500), nullable=True),
        sa.Column("bot_username", sa.String(length=100), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("bot_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("site_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("bot_status", sa.String(length=20), nullable=True),
        sa.Column("bot_status_detail", sa.String(length=300), nullable=True),
        sa.Column("bot_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vpn_notice_settings", sa.JSON(), nullable=True),
        sa.Column("suspend_policy", sa.String(length=20), server_default=sa.text("'none'"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name=op.f("fk_stores_owner_user_id_users")),
        sa.ForeignKeyConstraint(["parent_store_id"], ["stores.id"], name=op.f("fk_stores_parent_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
        sa.UniqueConstraint("domain", name=op.f("uq_stores_domain")),
        sa.UniqueConstraint("slug", name=op.f("uq_stores_slug")),
    )
    op.create_index(op.f("ix_stores_kind"), "stores", ["kind"], unique=False)
    op.create_index(op.f("ix_stores_owner_user_id"), "stores", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_stores_parent_store_id"), "stores", ["parent_store_id"], unique=False)
    op.create_table(
        "terms_acceptances",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("document", sa.String(length=20), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_terms_acceptances_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terms_acceptances")),
    )
    op.create_index(op.f("ix_terms_acceptances_user_id"), "terms_acceptances", ["user_id"], unique=False)
    op.create_table(
        "account_link_operations",
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("operation_type", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("subject_ref", sa.String(length=320), nullable=True),
        sa.Column("conflict_person_id", sa.Uuid(), nullable=True),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conflict_person_id"], ["persons.id"], name=op.f("fk_account_link_operations_conflict_person_id_persons")),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name=op.f("fk_account_link_operations_person_id_persons")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_account_link_operations_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_account_link_operations_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_link_operations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_account_link_operations_token_hash")),
    )
    op.create_index(op.f("ix_account_link_operations_expires_at"), "account_link_operations", ["expires_at"], unique=False)
    op.create_index(op.f("ix_account_link_operations_person_id"), "account_link_operations", ["person_id"], unique=False)
    op.create_index(op.f("ix_account_link_operations_status"), "account_link_operations", ["status"], unique=False)
    op.create_index(op.f("ix_account_link_operations_user_id"), "account_link_operations", ["user_id"], unique=False)
    op.create_table(
        "api_credentials",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False),
        sa.Column("ip_allowlist", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("rotated_from_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_api_credentials_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_credentials")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_credentials_key_hash")),
    )
    op.create_index(op.f("ix_api_credentials_key_prefix"), "api_credentials", ["key_prefix"], unique=False)
    op.create_index(op.f("ix_api_credentials_store_id"), "api_credentials", ["store_id"], unique=False)
    op.create_table(
        "bank_sms_sources",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("bank", sa.String(length=30), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_verify", sa.Boolean(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("token_hint", sa.String(length=8), nullable=True),
        sa.Column("senders", sa.JSON(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_bank_sms_sources_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bank_sms_sources")),
        sa.UniqueConstraint("store_id", name=op.f("uq_bank_sms_sources_store_id")),
    )
    op.create_index(op.f("ix_bank_sms_sources_store_id"), "bank_sms_sources", ["store_id"], unique=False)
    op.create_table(
        "bot_store_bindings",
        sa.Column("bot_key", sa.String(length=120), nullable=False),
        sa.Column("bot_username", sa.String(length=100), nullable=True),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("bot_kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name=op.f("fk_bot_store_bindings_owner_user_id_users")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_bot_store_bindings_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_store_bindings")),
        sa.UniqueConstraint("bot_key", name=op.f("uq_bot_store_bindings_bot_key")),
        sa.UniqueConstraint("store_id", name=op.f("uq_bot_store_bindings_store_id")),
    )
    op.create_index(op.f("ix_bot_store_bindings_owner_user_id"), "bot_store_bindings", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_bot_store_bindings_store_id"), "bot_store_bindings", ["store_id"], unique=False)
    op.create_table(
        "broadcasts",
        sa.Column("sender_user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("audience", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("recipients", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"], name=op.f("fk_broadcasts_sender_user_id_users")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_broadcasts_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broadcasts")),
    )
    op.create_index(op.f("ix_broadcasts_sender_user_id"), "broadcasts", ["sender_user_id"], unique=False)
    op.create_index(op.f("ix_broadcasts_store_id"), "broadcasts", ["store_id"], unique=False)
    op.create_table(
        "bulk_operations",
        sa.Column("panel_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("selection", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("succeeded", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("sample", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_bulk_operations_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], name=op.f("fk_bulk_operations_panel_id_panels"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_bulk_operations_store_id_stores"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bulk_operations")),
    )
    op.create_index(op.f("ix_bulk_operations_panel_id"), "bulk_operations", ["panel_id"], unique=False)
    op.create_index(op.f("ix_bulk_operations_status"), "bulk_operations", ["status"], unique=False)
    op.create_index("ix_bulk_operations_status_created", "bulk_operations", ["status", "created_at"], unique=False)
    op.create_index(op.f("ix_bulk_operations_store_id"), "bulk_operations", ["store_id"], unique=False)
    op.create_table(
        "commission_clawbacks",
        sa.Column("referrer_user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("outstanding", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"], name=op.f("fk_commission_clawbacks_referrer_user_id_users")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_commission_clawbacks_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commission_clawbacks")),
        sa.UniqueConstraint(
            "referrer_user_id", "store_id", "currency", name=op.f("uq_commission_clawbacks_referrer_user_id_store_id_currency")
        ),
    )
    op.create_index(op.f("ix_commission_clawbacks_referrer_user_id"), "commission_clawbacks", ["referrer_user_id"], unique=False)
    op.create_table(
        "commission_rules",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=10), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("max_amount", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_commission_rules_product_id_products")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_commission_rules_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commission_rules")),
        sa.UniqueConstraint("store_id", "product_id", "kind", name=op.f("uq_commission_rules_store_id_product_id_kind")),
    )
    op.create_index(op.f("ix_commission_rules_store_id"), "commission_rules", ["store_id"], unique=False)
    op.create_index(
        "uq_commission_rules_store_kind_default",
        "commission_rules",
        ["store_id", "kind"],
        unique=True,
        postgresql_where=sa.text("product_id IS NULL"),
        sqlite_where=sa.text("product_id IS NULL"),
    )
    op.create_table(
        "coupons",
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("owner_key", sa.String(length=64), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("allowed_store_ids", sa.JSON(), nullable=True),
        sa.Column("allowed_store_kinds", sa.JSON(), nullable=True),
        sa.Column("product_ids", sa.JSON(), nullable=True),
        sa.Column("creator_type", sa.String(length=10), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=True),
        sa.Column("funded_by", sa.String(length=10), nullable=False),
        sa.Column("percent_bp", sa.Integer(), nullable=False),
        sa.Column("fixed", sa.BigInteger(), nullable=False),
        sa.Column("max_discount", sa.BigInteger(), nullable=True),
        sa.Column("min_amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("per_customer_limit", sa.Integer(), nullable=True),
        sa.Column("redemptions", sa.Integer(), nullable=False),
        sa.Column("combinable", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_coupons_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coupons")),
        sa.UniqueConstraint("owner_key", "code", name=op.f("uq_coupons_owner_key_code")),
    )
    op.create_index(op.f("ix_coupons_code"), "coupons", ["code"], unique=False)
    op.create_index(op.f("ix_coupons_store_id"), "coupons", ["store_id"], unique=False)
    op.create_table(
        "file_objects",
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name=op.f("fk_file_objects_owner_user_id_users")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_file_objects_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_objects")),
    )
    op.create_index(op.f("ix_file_objects_owner_user_id"), "file_objects", ["owner_user_id"], unique=False)
    op.create_table(
        "ledger_transactions",
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("reverses_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("memo", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["reverses_id"], ["ledger_transactions.id"], name=op.f("fk_ledger_transactions_reverses_id_ledger_transactions")
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_ledger_transactions_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_transactions")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_ledger_transactions_idempotency_key")),
    )
    op.create_index(op.f("ix_ledger_transactions_kind"), "ledger_transactions", ["kind"], unique=False)
    op.create_index(op.f("ix_ledger_transactions_order_id"), "ledger_transactions", ["order_id"], unique=False)
    op.create_index(op.f("ix_ledger_transactions_payment_id"), "ledger_transactions", ["payment_id"], unique=False)
    op.create_index(op.f("ix_ledger_transactions_store_id"), "ledger_transactions", ["store_id"], unique=False)
    op.create_table(
        "loyalty_accounts",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False),
        sa.Column("lifetime_earned", sa.BigInteger(), nullable=False),
        sa.Column("debt", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("balance >= 0 AND debt >= 0", name=op.f("ck_loyalty_accounts_non_negative")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_loyalty_accounts_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_loyalty_accounts_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loyalty_accounts")),
        sa.UniqueConstraint("store_id", "user_id", name=op.f("uq_loyalty_accounts_store_id_user_id")),
    )
    op.create_index(op.f("ix_loyalty_accounts_store_id"), "loyalty_accounts", ["store_id"], unique=False)
    op.create_index(op.f("ix_loyalty_accounts_user_id"), "loyalty_accounts", ["user_id"], unique=False)
    op.create_table(
        "loyalty_programs",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("earn_unit", sa.BigInteger(), nullable=False),
        sa.Column("points_per_unit", sa.Integer(), nullable=False),
        sa.Column("max_points_per_order", sa.Integer(), nullable=True),
        sa.Column("first_order_bonus", sa.Integer(), nullable=False),
        sa.Column("referral_bonus", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_loyalty_programs_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loyalty_programs")),
        sa.UniqueConstraint("store_id", name=op.f("uq_loyalty_programs_store_id")),
    )
    op.create_index(op.f("ix_loyalty_programs_store_id"), "loyalty_programs", ["store_id"], unique=False)
    op.create_table(
        "loyalty_rewards",
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_loyalty_rewards_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loyalty_rewards")),
    )
    op.create_index(op.f("ix_loyalty_rewards_store_id"), "loyalty_rewards", ["store_id"], unique=False)
    op.create_table(
        "loyalty_tiers",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("min_points", sa.Integer(), nullable=False),
        sa.Column("multiplier_bp", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_loyalty_tiers_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loyalty_tiers")),
        sa.UniqueConstraint("store_id", "min_points", name=op.f("uq_loyalty_tiers_store_id_min_points")),
    )
    op.create_index(op.f("ix_loyalty_tiers_store_id"), "loyalty_tiers", ["store_id"], unique=False)
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("dedup_key", sa.String(length=200), nullable=True),
        sa.Column("telegram_status", sa.String(length=20), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_notifications_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("dedup_key", name=op.f("uq_notifications_dedup_key")),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_table(
        "orders",
        sa.Column("number", sa.String(length=6), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("renewal_mode", sa.String(length=10), server_default="replace", nullable=False),
        sa.Column("vpn_account_id", sa.Uuid(), nullable=True),
        sa.Column("bundle_id", sa.Uuid(), nullable=True),
        sa.Column("selected_panel_id", sa.Uuid(), nullable=True),
        sa.Column("allocated_server_id", sa.Uuid(), nullable=True),
        sa.Column("requested_account_name", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payment_method", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("unit_price", sa.BigInteger(), nullable=False),
        sa.Column("discount", sa.BigInteger(), nullable=False),
        sa.Column("total", sa.BigInteger(), nullable=False),
        sa.Column("reseller_cost", sa.BigInteger(), nullable=True),
        sa.Column("coupon_code", sa.String(length=50), nullable=True),
        sa.Column("pricing_snapshot", sa.JSON(), nullable=False),
        sa.Column("product_snapshot", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("provisioning_attempts", sa.Integer(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["allocated_server_id"], ["servers.id"], name=op.f("fk_orders_allocated_server_id_servers")),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"], name=op.f("fk_orders_bundle_id_bundles")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_orders_product_id_products")),
        sa.ForeignKeyConstraint(["selected_panel_id"], ["panels.id"], name=op.f("fk_orders_selected_panel_id_panels")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_orders_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_orders_user_id_users")),
        sa.ForeignKeyConstraint(
            ["vpn_account_id"], ["vpn_accounts.id"], name=op.f("fk_orders_vpn_account_id_vpn_accounts"), use_alter=True
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("number", name=op.f("uq_orders_number")),
        sa.UniqueConstraint("user_id", "store_id", "idempotency_key", name=op.f("uq_orders_user_id_store_id_idempotency_key")),
    )
    op.create_index(op.f("ix_orders_product_id"), "orders", ["product_id"], unique=False)
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)
    op.create_index(op.f("ix_orders_store_id"), "orders", ["store_id"], unique=False)
    op.create_index(op.f("ix_orders_user_id"), "orders", ["user_id"], unique=False)
    op.create_table(
        "panel_admin_change_requests",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_panel_admin_change_requests_requested_by_users")),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name=op.f("fk_panel_admin_change_requests_reviewed_by_users")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_panel_admin_change_requests_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_panel_admin_change_requests")),
    )
    op.create_index(op.f("ix_panel_admin_change_requests_status"), "panel_admin_change_requests", ["status"], unique=False)
    op.create_index(op.f("ix_panel_admin_change_requests_store_id"), "panel_admin_change_requests", ["store_id"], unique=False)
    op.create_index(
        "uq_panel_admin_request_one_pending",
        "panel_admin_change_requests",
        ["store_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "panel_admins",
        sa.Column("panel_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=34), nullable=False),
        sa.Column("password_enc", sa.Text(), nullable=True),
        sa.Column("remote_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("profile", sa.JSON(), nullable=True),
        sa.Column("profile_synced", sa.Boolean(), nullable=False),
        sa.Column("data_limit_bytes", sa.BigInteger(), nullable=True),
        sa.Column("usage_snapshot", sa.JSON(), nullable=True),
        sa.Column("usage_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("governance_error", sa.String(length=300), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], name=op.f("fk_panel_admins_panel_id_panels")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_panel_admins_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_panel_admins")),
        sa.UniqueConstraint("panel_id", "store_id", name="uq_panel_admins_panel_store"),
    )
    op.create_index(op.f("ix_panel_admins_panel_id"), "panel_admins", ["panel_id"], unique=False)
    op.create_index(op.f("ix_panel_admins_status"), "panel_admins", ["status"], unique=False)
    op.create_index(op.f("ix_panel_admins_store_id"), "panel_admins", ["store_id"], unique=False)
    op.create_index("uq_panel_admins_panel_username", "panel_admins", ["panel_id", "username"], unique=True)
    op.create_table(
        "referral_relationships",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("referrer_user_id", sa.Uuid(), nullable=False),
        sa.Column("referred_user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"], name=op.f("fk_referral_relationships_referred_user_id_users")),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"], name=op.f("fk_referral_relationships_referrer_user_id_users")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_referral_relationships_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_referral_relationships")),
        sa.UniqueConstraint("store_id", "referred_user_id", name=op.f("uq_referral_relationships_store_id_referred_user_id")),
    )
    op.create_index(op.f("ix_referral_relationships_referrer_user_id"), "referral_relationships", ["referrer_user_id"], unique=False)
    op.create_index(op.f("ix_referral_relationships_store_id"), "referral_relationships", ["store_id"], unique=False)
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("channel", sa.String(length=10), nullable=True),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_refresh_tokens_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_refresh_tokens_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False)
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "reseller_applications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_name", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_store_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("bot_token_enc", sa.String(length=500), nullable=True),
        sa.Column("bot_key", sa.String(length=120), nullable=True),
        sa.Column("bot_username", sa.String(length=100), nullable=True),
        sa.Column("bot_verified", sa.Boolean(), nullable=False),
        sa.Column("review_reason", sa.String(length=500), nullable=True),
        sa.Column("approved_debt_limit", sa.BigInteger(), nullable=True),
        sa.Column("domain_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("domain_method", sa.String(length=10), nullable=True),
        sa.Column("verify_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("verify_next_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verify_error", sa.String(length=200), nullable=True),
        sa.Column("auto_approved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("recheck_next_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recheck_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("recheck_error", sa.String(length=200), nullable=True),
        sa.Column("identity_lost_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name=op.f("fk_reseller_applications_reviewed_by_users")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_reseller_applications_store_id_stores")),
        sa.ForeignKeyConstraint(["target_store_id"], ["stores.id"], name=op.f("fk_reseller_applications_target_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_reseller_applications_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reseller_applications")),
    )
    op.create_index(op.f("ix_reseller_applications_target_store_id"), "reseller_applications", ["target_store_id"], unique=False)
    op.create_index(op.f("ix_reseller_applications_user_id"), "reseller_applications", ["user_id"], unique=False)
    op.create_index(
        "uq_reseller_application_pending_bot",
        "reseller_applications",
        ["bot_key"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_reseller_application_pending_domain",
        "reseller_applications",
        ["domain"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_reseller_application_pending_user_store",
        "reseller_applications",
        ["user_id", "target_store_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "reseller_profiles",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("debt_limit", sa.BigInteger(), nullable=False),
        sa.Column("api_enabled", sa.Boolean(), nullable=False),
        sa.Column("sales_enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_reseller_profiles_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_reseller_profiles_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reseller_profiles")),
        sa.UniqueConstraint("store_id", name=op.f("uq_reseller_profiles_store_id")),
    )
    op.create_index(op.f("ix_reseller_profiles_user_id"), "reseller_profiles", ["user_id"], unique=False)
    op.create_table(
        "store_bundle_prices",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("customer_price", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"], name=op.f("fk_store_bundle_prices_bundle_id_bundles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_store_bundle_prices_product_id_products"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_store_bundle_prices_store_id_stores"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_bundle_prices")),
        sa.UniqueConstraint("store_id", "bundle_id", "product_id", name=op.f("uq_store_bundle_prices_store_id_bundle_id_product_id")),
    )
    op.create_index(op.f("ix_store_bundle_prices_bundle_id"), "store_bundle_prices", ["bundle_id"], unique=False)
    op.create_index(op.f("ix_store_bundle_prices_product_id"), "store_bundle_prices", ["product_id"], unique=False)
    op.create_index(op.f("ix_store_bundle_prices_store_id"), "store_bundle_prices", ["store_id"], unique=False)
    op.create_table(
        "store_bundles",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundles.id"], name=op.f("fk_store_bundles_bundle_id_bundles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_store_bundles_store_id_stores"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_bundles")),
        sa.UniqueConstraint("store_id", "bundle_id", name=op.f("uq_store_bundles_store_id_bundle_id")),
    )
    op.create_index(op.f("ix_store_bundles_bundle_id"), "store_bundles", ["bundle_id"], unique=False)
    op.create_index(op.f("ix_store_bundles_store_id"), "store_bundles", ["store_id"], unique=False)
    op.create_table(
        "store_memberships",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_store_memberships_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_store_memberships_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_memberships")),
        sa.UniqueConstraint("store_id", "user_id", name=op.f("uq_store_memberships_store_id_user_id")),
    )
    op.create_index(op.f("ix_store_memberships_store_id"), "store_memberships", ["store_id"], unique=False)
    op.create_index(op.f("ix_store_memberships_user_id"), "store_memberships", ["user_id"], unique=False)
    op.create_table(
        "store_payment_configurations",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("public_config", sa.JSON(), nullable=True),
        sa.Column("secret_enc", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_store_payment_configurations_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_payment_configurations")),
        sa.UniqueConstraint("store_id", "provider", name=op.f("uq_store_payment_configurations_store_id_provider")),
    )
    op.create_index(op.f("ix_store_payment_configurations_store_id"), "store_payment_configurations", ["store_id"], unique=False)
    op.create_table(
        "store_products",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("customer_price", sa.BigInteger(), nullable=True),
        sa.Column("is_listed", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_store_products_product_id_products")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_store_products_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_products")),
        sa.UniqueConstraint("store_id", "product_id", name=op.f("uq_store_products_store_id_product_id")),
    )
    op.create_index(op.f("ix_store_products_product_id"), "store_products", ["product_id"], unique=False)
    op.create_index(op.f("ix_store_products_store_id"), "store_products", ["store_id"], unique=False)
    op.create_table(
        "telegram_event_destinations",
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("chat_id", sa.String(length=50), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_telegram_event_destinations_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_event_destinations")),
        sa.UniqueConstraint("store_id", name=op.f("uq_telegram_event_destinations_store_id")),
    )
    op.create_table(
        "telegram_login_sessions",
        sa.Column("public_id", sa.String(length=24), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("match_code", sa.String(length=2), nullable=False),
        sa.Column("decoys", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("req_ip", sa.String(length=64), nullable=True),
        sa.Column("req_device", sa.String(length=120), nullable=True),
        sa.Column("req_ua", sa.String(length=300), nullable=True),
        sa.Column("scanned_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("deny_reason", sa.String(length=40), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_key_hash", sa.String(length=64), nullable=True),
        sa.Column("remember", sa.Boolean(), nullable=False),
        sa.Column("auto_level", sa.String(length=12), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_telegram_login_sessions_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_telegram_login_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_login_sessions")),
        sa.UniqueConstraint("public_id", name=op.f("uq_telegram_login_sessions_public_id")),
    )
    op.create_index(op.f("ix_telegram_login_sessions_device_key_hash"), "telegram_login_sessions", ["device_key_hash"], unique=False)
    op.create_index(op.f("ix_telegram_login_sessions_expires_at"), "telegram_login_sessions", ["expires_at"], unique=False)
    op.create_index(op.f("ix_telegram_login_sessions_status"), "telegram_login_sessions", ["status"], unique=False)
    op.create_index(op.f("ix_telegram_login_sessions_store_id"), "telegram_login_sessions", ["store_id"], unique=False)
    op.create_table(
        "tickets",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=6), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=10), server_default="normal", nullable=False),
        sa.Column("department", sa.String(length=50), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_tickets_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_tickets_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
    )
    op.create_index(op.f("ix_tickets_number"), "tickets", ["number"], unique=True)
    op.create_index(op.f("ix_tickets_priority"), "tickets", ["priority"], unique=False)
    op.create_index(op.f("ix_tickets_status"), "tickets", ["status"], unique=False)
    op.create_index(op.f("ix_tickets_store_id"), "tickets", ["store_id"], unique=False)
    op.create_index(op.f("ix_tickets_user_id"), "tickets", ["user_id"], unique=False)
    op.create_table(
        "trusted_devices",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("last_ip", sa.String(length=64), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_trusted_devices_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_trusted_devices_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trusted_devices")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_trusted_devices_key_hash")),
    )
    op.create_index(op.f("ix_trusted_devices_expires_at"), "trusted_devices", ["expires_at"], unique=False)
    op.create_index(op.f("ix_trusted_devices_store_id"), "trusted_devices", ["store_id"], unique=False)
    op.create_index(op.f("ix_trusted_devices_telegram_id"), "trusted_devices", ["telegram_id"], unique=False)
    op.create_index(op.f("ix_trusted_devices_user_id"), "trusted_devices", ["user_id"], unique=False)
    op.create_table(
        "verification_codes",
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("target", sa.String(length=320), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_verification_codes_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_verification_codes_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_codes")),
    )
    op.create_index(op.f("ix_verification_codes_code_hash"), "verification_codes", ["code_hash"], unique=False)
    op.create_index(op.f("ix_verification_codes_purpose"), "verification_codes", ["purpose"], unique=False)
    op.create_index(op.f("ix_verification_codes_target"), "verification_codes", ["target"], unique=False)
    op.create_table(
        "wallets",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="active", nullable=False),
        sa.Column("consolidated_into_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["consolidated_into_id"], ["wallets.id"], name=op.f("fk_wallets_consolidated_into_id_wallets")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_wallets_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_wallets_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallets")),
        sa.UniqueConstraint("user_id", "store_id", "kind", "currency", name=op.f("uq_wallets_user_id_store_id_kind_currency")),
    )
    op.create_index(op.f("ix_wallets_store_id"), "wallets", ["store_id"], unique=False)
    op.create_index(op.f("ix_wallets_user_id"), "wallets", ["user_id"], unique=False)
    op.create_table(
        "webhook_endpoints",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("secret_enc", sa.Text(), nullable=False),
        sa.Column("previous_secret_enc", sa.Text(), nullable=True),
        sa.Column("previous_secret_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_webhook_endpoints_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_endpoints")),
    )
    op.create_index(op.f("ix_webhook_endpoints_store_id"), "webhook_endpoints", ["store_id"], unique=False)
    op.create_table(
        "account_link_evidence",
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("subject_reference", sa.String(length=320), nullable=True),
        sa.Column("result", sa.String(length=12), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["account_link_operations.id"], name=op.f("fk_account_link_evidence_operation_id_account_link_operations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_link_evidence")),
    )
    op.create_index(op.f("ix_account_link_evidence_operation_id"), "account_link_evidence", ["operation_id"], unique=False)
    op.create_table(
        "admin_tasks",
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("done_by", sa.Uuid(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"], ["reseller_applications.id"], name=op.f("fk_admin_tasks_application_id_reseller_applications")
        ),
        sa.ForeignKeyConstraint(["done_by"], ["users.id"], name=op.f("fk_admin_tasks_done_by_users")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_admin_tasks_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_tasks")),
        sa.UniqueConstraint("kind", "application_id", name="uq_admin_tasks_kind_application"),
    )
    op.create_index(op.f("ix_admin_tasks_application_id"), "admin_tasks", ["application_id"], unique=False)
    op.create_index(op.f("ix_admin_tasks_kind"), "admin_tasks", ["kind"], unique=False)
    op.create_index(op.f("ix_admin_tasks_status"), "admin_tasks", ["status"], unique=False)
    op.create_table(
        "commissions",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("referrer_user_id", sa.Uuid(), nullable=False),
        sa.Column("referred_user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("ledger_tx_id", sa.Uuid(), nullable=True),
        sa.Column("reversed_amount", sa.BigInteger(), nullable=False),
        sa.Column("offset_amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_commissions_order_id_orders")),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"], name=op.f("fk_commissions_referred_user_id_users")),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"], name=op.f("fk_commissions_referrer_user_id_users")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_commissions_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commissions")),
        sa.UniqueConstraint("order_id", "kind", name=op.f("uq_commissions_order_id_kind")),
    )
    op.create_index(op.f("ix_commissions_referred_user_id"), "commissions", ["referred_user_id"], unique=False)
    op.create_index(op.f("ix_commissions_referrer_user_id"), "commissions", ["referrer_user_id"], unique=False)
    op.create_index(op.f("ix_commissions_store_id"), "commissions", ["store_id"], unique=False)
    op.create_index(
        "uq_commissions_store_referred_signup_reward",
        "commissions",
        ["store_id", "referred_user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'signup_reward'"),
        sqlite_where=sa.text("kind = 'signup_reward'"),
    )
    op.create_table(
        "coupon_redemptions",
        sa.Column("coupon_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"], name=op.f("fk_coupon_redemptions_coupon_id_coupons")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_coupon_redemptions_order_id_orders")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_coupon_redemptions_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_coupon_redemptions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coupon_redemptions")),
        sa.UniqueConstraint("coupon_id", "order_id", name=op.f("uq_coupon_redemptions_coupon_id_order_id")),
    )
    op.create_index(op.f("ix_coupon_redemptions_coupon_id"), "coupon_redemptions", ["coupon_id"], unique=False)
    op.create_index(op.f("ix_coupon_redemptions_order_id"), "coupon_redemptions", ["order_id"], unique=False)
    op.create_index(op.f("ix_coupon_redemptions_store_id"), "coupon_redemptions", ["store_id"], unique=False)
    op.create_index(op.f("ix_coupon_redemptions_user_id"), "coupon_redemptions", ["user_id"], unique=False)
    op.create_table(
        "ledger_entries",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("account", sa.String(length=120), nullable=False),
        sa.Column("wallet_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["ledger_transactions.id"], name=op.f("fk_ledger_entries_transaction_id_ledger_transactions")
        ),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], name=op.f("fk_ledger_entries_wallet_id_wallets")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_entries")),
    )
    op.create_index(op.f("ix_ledger_entries_account"), "ledger_entries", ["account"], unique=False)
    op.create_index(op.f("ix_ledger_entries_transaction_id"), "ledger_entries", ["transaction_id"], unique=False)
    op.create_index(op.f("ix_ledger_entries_wallet_id"), "ledger_entries", ["wallet_id"], unique=False)
    op.create_table(
        "loyalty_redemptions",
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["reward_id"], ["loyalty_rewards.id"], name=op.f("fk_loyalty_redemptions_reward_id_loyalty_rewards")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_loyalty_redemptions_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_loyalty_redemptions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loyalty_redemptions")),
        sa.UniqueConstraint("store_id", "user_id", "idempotency_key", name=op.f("uq_loyalty_redemptions_store_id_user_id_idempotency_key")),
    )
    op.create_index(op.f("ix_loyalty_redemptions_reward_id"), "loyalty_redemptions", ["reward_id"], unique=False)
    op.create_index(op.f("ix_loyalty_redemptions_store_id"), "loyalty_redemptions", ["store_id"], unique=False)
    op.create_index(op.f("ix_loyalty_redemptions_user_id"), "loyalty_redemptions", ["user_id"], unique=False)
    op.create_table(
        "loyalty_transactions",
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["loyalty_accounts.id"], name=op.f("fk_loyalty_transactions_account_id_loyalty_accounts")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_loyalty_transactions_order_id_orders")),
        sa.ForeignKeyConstraint(
            ["reverses_id"], ["loyalty_transactions.id"], name=op.f("fk_loyalty_transactions_reverses_id_loyalty_transactions")
        ),
        sa.ForeignKeyConstraint(["reward_id"], ["loyalty_rewards.id"], name=op.f("fk_loyalty_transactions_reward_id_loyalty_rewards")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_loyalty_transactions_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_loyalty_transactions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loyalty_transactions")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_loyalty_transactions_idempotency_key")),
    )
    op.create_index(op.f("ix_loyalty_transactions_account_id"), "loyalty_transactions", ["account_id"], unique=False)
    op.create_index(op.f("ix_loyalty_transactions_order_id"), "loyalty_transactions", ["order_id"], unique=False)
    op.create_index(op.f("ix_loyalty_transactions_store_id"), "loyalty_transactions", ["store_id"], unique=False)
    op.create_index(
        "ix_loyalty_transactions_store_user_created", "loyalty_transactions", ["store_id", "user_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_loyalty_transactions_user_id"), "loyalty_transactions", ["user_id"], unique=False)
    op.create_table(
        "order_state_transitions",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=False),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_order_state_transitions_order_id_orders")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_state_transitions")),
    )
    op.create_index(op.f("ix_order_state_transitions_order_id"), "order_state_transitions", ["order_id"], unique=False)
    op.create_table(
        "payments",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("external_ref", sa.String(length=200), nullable=True),
        sa.Column("receipt_file_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_payments_order_id_orders")),
        sa.ForeignKeyConstraint(["receipt_file_id"], ["file_objects.id"], name=op.f("fk_payments_receipt_file_id_file_objects")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_payments_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_payments_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("provider", "external_ref", name=op.f("uq_payments_provider_external_ref")),
        sa.UniqueConstraint("user_id", "store_id", "idempotency_key", name=op.f("uq_payments_user_id_store_id_idempotency_key")),
    )
    op.create_index(op.f("ix_payments_order_id"), "payments", ["order_id"], unique=False)
    op.create_index(op.f("ix_payments_status"), "payments", ["status"], unique=False)
    op.create_index(op.f("ix_payments_store_id"), "payments", ["store_id"], unique=False)
    op.create_index(op.f("ix_payments_user_id"), "payments", ["user_id"], unique=False)
    op.create_table(
        "test_account_grants",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("identity_keys", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_test_account_grants_order_id_orders")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_test_account_grants_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_test_account_grants_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_account_grants")),
    )
    op.create_index(op.f("ix_test_account_grants_user_id"), "test_account_grants", ["user_id"], unique=False)
    op.create_table(
        "ticket_messages",
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("is_staff", sa.Boolean(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["file_objects.id"], name=op.f("fk_ticket_messages_attachment_id_file_objects")),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], name=op.f("fk_ticket_messages_author_id_users")),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_messages_ticket_id_tickets")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_messages")),
    )
    op.create_index(op.f("ix_ticket_messages_ticket_id"), "ticket_messages", ["ticket_id"], unique=False)
    op.create_table(
        "vpn_accounts",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=True),
        sa.Column("panel_id", sa.Uuid(), nullable=True),
        sa.Column("panel_ref", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.Column("sold_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sold_traffic_bytes", sa.BigInteger(), nullable=False),
        sa.Column("delivery_snapshot", sa.JSON(), nullable=True),
        sa.Column("near_expiry_notified", sa.Boolean(), nullable=False),
        sa.Column("traffic_notified_level", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_plan", sa.JSON(), nullable=True),
        sa.Column("placement", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_vpn_accounts_order_id_orders")),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], name=op.f("fk_vpn_accounts_panel_id_panels")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_vpn_accounts_product_id_products")),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], name=op.f("fk_vpn_accounts_server_id_servers")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_vpn_accounts_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_vpn_accounts_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vpn_accounts")),
        sa.UniqueConstraint("username", name=op.f("uq_vpn_accounts_username")),
    )
    op.create_index(op.f("ix_vpn_accounts_last_synced_at"), "vpn_accounts", ["last_synced_at"], unique=False)
    op.create_index(op.f("ix_vpn_accounts_order_id"), "vpn_accounts", ["order_id"], unique=False)
    op.create_index(op.f("ix_vpn_accounts_server_id"), "vpn_accounts", ["server_id"], unique=False)
    op.create_index(op.f("ix_vpn_accounts_sold_expires_at"), "vpn_accounts", ["sold_expires_at"], unique=False)
    op.create_index(op.f("ix_vpn_accounts_status"), "vpn_accounts", ["status"], unique=False)
    op.create_index(op.f("ix_vpn_accounts_store_id"), "vpn_accounts", ["store_id"], unique=False)
    op.create_index(op.f("ix_vpn_accounts_user_id"), "vpn_accounts", ["user_id"], unique=False)
    op.create_table(
        "wallet_transfers",
        sa.Column("consolidation_id", sa.Uuid(), nullable=False),
        sa.Column("source_wallet_id", sa.Uuid(), nullable=False),
        sa.Column("target_wallet_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("ledger_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["consolidation_id"],
            ["account_consolidation_operations.id"],
            name=op.f("fk_wallet_transfers_consolidation_id_account_consolidation_operations"),
        ),
        sa.ForeignKeyConstraint(
            ["ledger_transaction_id"],
            ["ledger_transactions.id"],
            name=op.f("fk_wallet_transfers_ledger_transaction_id_ledger_transactions"),
        ),
        sa.ForeignKeyConstraint(["source_wallet_id"], ["wallets.id"], name=op.f("fk_wallet_transfers_source_wallet_id_wallets")),
        sa.ForeignKeyConstraint(["target_wallet_id"], ["wallets.id"], name=op.f("fk_wallet_transfers_target_wallet_id_wallets")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallet_transfers")),
    )
    op.create_index(op.f("ix_wallet_transfers_consolidation_id"), "wallet_transfers", ["consolidation_id"], unique=False)
    op.create_index(op.f("ix_wallet_transfers_source_wallet_id"), "wallet_transfers", ["source_wallet_id"], unique=False)
    op.create_index(op.f("ix_wallet_transfers_target_wallet_id"), "wallet_transfers", ["target_wallet_id"], unique=False)
    op.create_table(
        "webhook_deliveries",
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_response_ms", sa.Integer(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["endpoint_id"], ["webhook_endpoints.id"], name=op.f("fk_webhook_deliveries_endpoint_id_webhook_endpoints")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
        sa.UniqueConstraint("endpoint_id", "event_id", name=op.f("uq_webhook_deliveries_endpoint_id_event_id")),
    )
    op.create_index(op.f("ix_webhook_deliveries_endpoint_id"), "webhook_deliveries", ["endpoint_id"], unique=False)
    op.create_index(op.f("ix_webhook_deliveries_event_type"), "webhook_deliveries", ["event_type"], unique=False)
    op.create_index(op.f("ix_webhook_deliveries_next_attempt_at"), "webhook_deliveries", ["next_attempt_at"], unique=False)
    op.create_index(op.f("ix_webhook_deliveries_status"), "webhook_deliveries", ["status"], unique=False)
    op.create_index(op.f("ix_webhook_deliveries_store_id"), "webhook_deliveries", ["store_id"], unique=False)
    op.create_table(
        "account_returns",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("vpn_account_id", sa.Uuid(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_account_returns_order_id_orders")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_account_returns_store_id_stores")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_account_returns_user_id_users")),
        sa.ForeignKeyConstraint(["vpn_account_id"], ["vpn_accounts.id"], name=op.f("fk_account_returns_vpn_account_id_vpn_accounts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_returns")),
        sa.UniqueConstraint("order_id", name=op.f("uq_account_returns_order_id")),
    )
    op.create_index(op.f("ix_account_returns_store_id"), "account_returns", ["store_id"], unique=False)
    op.create_index(op.f("ix_account_returns_user_id"), "account_returns", ["user_id"], unique=False)
    op.create_index(op.f("ix_account_returns_vpn_account_id"), "account_returns", ["vpn_account_id"], unique=False)
    op.create_table(
        "bank_sms_messages",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("serial", sa.String(length=64), nullable=True),
        sa.Column("direction", sa.String(length=12), nullable=True),
        sa.Column("amount_rial", sa.BigInteger(), nullable=True),
        sa.Column("balance_rial", sa.BigInteger(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sender", sa.String(length=64), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("matched_by", sa.String(length=10), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("balance_gap", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name=op.f("fk_bank_sms_messages_payment_id_payments")),
        sa.ForeignKeyConstraint(["source_id"], ["bank_sms_sources.id"], name=op.f("fk_bank_sms_messages_source_id_bank_sms_sources")),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_bank_sms_messages_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bank_sms_messages")),
        sa.UniqueConstraint("payment_id", name=op.f("uq_bank_sms_messages_payment_id")),
        sa.UniqueConstraint("store_id", "fingerprint", name=op.f("uq_bank_sms_messages_store_id_fingerprint")),
    )
    op.create_index(op.f("ix_bank_sms_messages_occurred_at"), "bank_sms_messages", ["occurred_at"], unique=False)
    op.create_index(op.f("ix_bank_sms_messages_status"), "bank_sms_messages", ["status"], unique=False)
    op.create_index(op.f("ix_bank_sms_messages_store_id"), "bank_sms_messages", ["store_id"], unique=False)
    op.create_table(
        "bulk_operation_items",
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("vpn_account_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("panel_ref", sa.String(length=200), nullable=True),
        sa.Column("target", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["bulk_operations.id"], name=op.f("fk_bulk_operation_items_operation_id_bulk_operations"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["vpn_account_id"], ["vpn_accounts.id"], name=op.f("fk_bulk_operation_items_vpn_account_id_vpn_accounts"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bulk_operation_items")),
        sa.UniqueConstraint("operation_id", "vpn_account_id", name="uq_bulk_items_operation_account"),
    )
    op.create_index(op.f("ix_bulk_operation_items_operation_id"), "bulk_operation_items", ["operation_id"], unique=False)
    op.create_index(op.f("ix_bulk_operation_items_status"), "bulk_operation_items", ["status"], unique=False)
    op.create_index(op.f("ix_bulk_operation_items_vpn_account_id"), "bulk_operation_items", ["vpn_account_id"], unique=False)
    op.create_table(
        "panel_events",
        sa.Column("panel_id", sa.Uuid(), nullable=False),
        sa.Column("dedup_key", sa.String(length=200), nullable=False),
        sa.Column("event_id", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=200), nullable=True),
        sa.Column("vpn_account_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], name=op.f("fk_panel_events_panel_id_panels"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["vpn_account_id"], ["vpn_accounts.id"], name=op.f("fk_panel_events_vpn_account_id_vpn_accounts"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_panel_events")),
        sa.UniqueConstraint("panel_id", "dedup_key", name="uq_panel_events_dedup"),
    )
    op.create_index(op.f("ix_panel_events_panel_id"), "panel_events", ["panel_id"], unique=False)
    op.create_index("ix_panel_events_queue", "panel_events", ["status", "available_at"], unique=False)
    op.create_index(op.f("ix_panel_events_received_at"), "panel_events", ["received_at"], unique=False)
    op.create_table(
        "payment_attempts",
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name=op.f("fk_payment_attempts_payment_id_payments")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_attempts")),
    )
    op.create_index(op.f("ix_payment_attempts_payment_id"), "payment_attempts", ["payment_id"], unique=False)
    op.create_table(
        "payment_receipt_fingerprints",
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("file_unique_id", sa.String(length=128), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_payment_receipt_fingerprints_payment_id_payments"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name=op.f("fk_payment_receipt_fingerprints_store_id_stores")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_receipt_fingerprints")),
    )
    op.create_index(op.f("ix_payment_receipt_fingerprints_payment_id"), "payment_receipt_fingerprints", ["payment_id"], unique=False)
    op.create_index(op.f("ix_payment_receipt_fingerprints_store_id"), "payment_receipt_fingerprints", ["store_id"], unique=False)
    op.create_index("ix_receipt_fp_file_unique_id", "payment_receipt_fingerprints", ["file_unique_id"], unique=False)
    op.create_index("ix_receipt_fp_sha256", "payment_receipt_fingerprints", ["sha256"], unique=False)
    op.create_table(
        "provisioning_attempts",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("vpn_account_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_kind", sa.String(length=20), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_provisioning_attempts_order_id_orders")),
        sa.ForeignKeyConstraint(["vpn_account_id"], ["vpn_accounts.id"], name=op.f("fk_provisioning_attempts_vpn_account_id_vpn_accounts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provisioning_attempts")),
        sa.UniqueConstraint("order_id", "attempt_no", name=op.f("uq_provisioning_attempts_order_id_attempt_no")),
    )
    op.create_index(op.f("ix_provisioning_attempts_order_id"), "provisioning_attempts", ["order_id"], unique=False)
    op.create_table(
        "reconciliation_issues",
        sa.Column("vpn_account_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=300), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vpn_account_id"], ["vpn_accounts.id"], name=op.f("fk_reconciliation_issues_vpn_account_id_vpn_accounts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reconciliation_issues")),
    )
    op.create_index(op.f("ix_reconciliation_issues_vpn_account_id"), "reconciliation_issues", ["vpn_account_id"], unique=False)
    op.create_index(
        "uq_reconciliation_issue_open",
        "reconciliation_issues",
        ["vpn_account_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
        sqlite_where=sa.text("status = 'open'"),
    )

    # orders <-> vpn_accounts reference each other, so this one FK is added after both tables exist (SQLite tests build the schema from metadata).
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(op.f("fk_orders_vpn_account_id_vpn_accounts"), "orders", "vpn_accounts", ["vpn_account_id"], ["id"])
    for table in _APPEND_ONLY_TABLES:
        _append_only(table)
    settings = sa.table("system_settings", sa.column("id", sa.Uuid()), sa.column("key", sa.String()), sa.column("value", sa.JSON()))
    op.bulk_insert(settings, [{"id": uuid.uuid4(), "key": k, "value": v} for k, v in _SETTINGS])


def downgrade() -> None:
    for table in _APPEND_ONLY_TABLES:
        _drop_append_only(table)
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(op.f("fk_orders_vpn_account_id_vpn_accounts"), "orders", type_="foreignkey")
    op.drop_index(
        "uq_reconciliation_issue_open",
        table_name="reconciliation_issues",
        postgresql_where=sa.text("status = 'open'"),
        sqlite_where=sa.text("status = 'open'"),
    )
    op.drop_index(op.f("ix_reconciliation_issues_vpn_account_id"), table_name="reconciliation_issues")
    op.drop_table("reconciliation_issues")
    op.drop_index(op.f("ix_provisioning_attempts_order_id"), table_name="provisioning_attempts")
    op.drop_table("provisioning_attempts")
    op.drop_index("ix_receipt_fp_sha256", table_name="payment_receipt_fingerprints")
    op.drop_index("ix_receipt_fp_file_unique_id", table_name="payment_receipt_fingerprints")
    op.drop_index(op.f("ix_payment_receipt_fingerprints_store_id"), table_name="payment_receipt_fingerprints")
    op.drop_index(op.f("ix_payment_receipt_fingerprints_payment_id"), table_name="payment_receipt_fingerprints")
    op.drop_table("payment_receipt_fingerprints")
    op.drop_index(op.f("ix_payment_attempts_payment_id"), table_name="payment_attempts")
    op.drop_table("payment_attempts")
    op.drop_index(op.f("ix_panel_events_received_at"), table_name="panel_events")
    op.drop_index("ix_panel_events_queue", table_name="panel_events")
    op.drop_index(op.f("ix_panel_events_panel_id"), table_name="panel_events")
    op.drop_table("panel_events")
    op.drop_index(op.f("ix_bulk_operation_items_vpn_account_id"), table_name="bulk_operation_items")
    op.drop_index(op.f("ix_bulk_operation_items_status"), table_name="bulk_operation_items")
    op.drop_index(op.f("ix_bulk_operation_items_operation_id"), table_name="bulk_operation_items")
    op.drop_table("bulk_operation_items")
    op.drop_index(op.f("ix_bank_sms_messages_store_id"), table_name="bank_sms_messages")
    op.drop_index(op.f("ix_bank_sms_messages_status"), table_name="bank_sms_messages")
    op.drop_index(op.f("ix_bank_sms_messages_occurred_at"), table_name="bank_sms_messages")
    op.drop_table("bank_sms_messages")
    op.drop_index(op.f("ix_account_returns_vpn_account_id"), table_name="account_returns")
    op.drop_index(op.f("ix_account_returns_user_id"), table_name="account_returns")
    op.drop_index(op.f("ix_account_returns_store_id"), table_name="account_returns")
    op.drop_table("account_returns")
    op.drop_index(op.f("ix_webhook_deliveries_store_id"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_status"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_next_attempt_at"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_event_type"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_endpoint_id"), table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index(op.f("ix_wallet_transfers_target_wallet_id"), table_name="wallet_transfers")
    op.drop_index(op.f("ix_wallet_transfers_source_wallet_id"), table_name="wallet_transfers")
    op.drop_index(op.f("ix_wallet_transfers_consolidation_id"), table_name="wallet_transfers")
    op.drop_table("wallet_transfers")
    op.drop_index(op.f("ix_vpn_accounts_user_id"), table_name="vpn_accounts")
    op.drop_index(op.f("ix_vpn_accounts_store_id"), table_name="vpn_accounts")
    op.drop_index(op.f("ix_vpn_accounts_status"), table_name="vpn_accounts")
    op.drop_index(op.f("ix_vpn_accounts_sold_expires_at"), table_name="vpn_accounts")
    op.drop_index(op.f("ix_vpn_accounts_server_id"), table_name="vpn_accounts")
    op.drop_index(op.f("ix_vpn_accounts_order_id"), table_name="vpn_accounts")
    op.drop_index(op.f("ix_vpn_accounts_last_synced_at"), table_name="vpn_accounts")
    op.drop_table("vpn_accounts")
    op.drop_index(op.f("ix_ticket_messages_ticket_id"), table_name="ticket_messages")
    op.drop_table("ticket_messages")
    op.drop_index(op.f("ix_test_account_grants_user_id"), table_name="test_account_grants")
    op.drop_table("test_account_grants")
    op.drop_index(op.f("ix_payments_user_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_store_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_status"), table_name="payments")
    op.drop_index(op.f("ix_payments_order_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_index(op.f("ix_order_state_transitions_order_id"), table_name="order_state_transitions")
    op.drop_table("order_state_transitions")
    op.drop_index(op.f("ix_loyalty_transactions_user_id"), table_name="loyalty_transactions")
    op.drop_index("ix_loyalty_transactions_store_user_created", table_name="loyalty_transactions")
    op.drop_index(op.f("ix_loyalty_transactions_store_id"), table_name="loyalty_transactions")
    op.drop_index(op.f("ix_loyalty_transactions_order_id"), table_name="loyalty_transactions")
    op.drop_index(op.f("ix_loyalty_transactions_account_id"), table_name="loyalty_transactions")
    op.drop_table("loyalty_transactions")
    op.drop_index(op.f("ix_loyalty_redemptions_user_id"), table_name="loyalty_redemptions")
    op.drop_index(op.f("ix_loyalty_redemptions_store_id"), table_name="loyalty_redemptions")
    op.drop_index(op.f("ix_loyalty_redemptions_reward_id"), table_name="loyalty_redemptions")
    op.drop_table("loyalty_redemptions")
    op.drop_index(op.f("ix_ledger_entries_wallet_id"), table_name="ledger_entries")
    op.drop_index(op.f("ix_ledger_entries_transaction_id"), table_name="ledger_entries")
    op.drop_index(op.f("ix_ledger_entries_account"), table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index(op.f("ix_coupon_redemptions_user_id"), table_name="coupon_redemptions")
    op.drop_index(op.f("ix_coupon_redemptions_store_id"), table_name="coupon_redemptions")
    op.drop_index(op.f("ix_coupon_redemptions_order_id"), table_name="coupon_redemptions")
    op.drop_index(op.f("ix_coupon_redemptions_coupon_id"), table_name="coupon_redemptions")
    op.drop_table("coupon_redemptions")
    op.drop_index(
        "uq_commissions_store_referred_signup_reward",
        table_name="commissions",
        postgresql_where=sa.text("kind = 'signup_reward'"),
        sqlite_where=sa.text("kind = 'signup_reward'"),
    )
    op.drop_index(op.f("ix_commissions_store_id"), table_name="commissions")
    op.drop_index(op.f("ix_commissions_referrer_user_id"), table_name="commissions")
    op.drop_index(op.f("ix_commissions_referred_user_id"), table_name="commissions")
    op.drop_table("commissions")
    op.drop_index(op.f("ix_admin_tasks_status"), table_name="admin_tasks")
    op.drop_index(op.f("ix_admin_tasks_kind"), table_name="admin_tasks")
    op.drop_index(op.f("ix_admin_tasks_application_id"), table_name="admin_tasks")
    op.drop_table("admin_tasks")
    op.drop_index(op.f("ix_account_link_evidence_operation_id"), table_name="account_link_evidence")
    op.drop_table("account_link_evidence")
    op.drop_index(op.f("ix_webhook_endpoints_store_id"), table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
    op.drop_index(op.f("ix_wallets_user_id"), table_name="wallets")
    op.drop_index(op.f("ix_wallets_store_id"), table_name="wallets")
    op.drop_table("wallets")
    op.drop_index(op.f("ix_verification_codes_target"), table_name="verification_codes")
    op.drop_index(op.f("ix_verification_codes_purpose"), table_name="verification_codes")
    op.drop_index(op.f("ix_verification_codes_code_hash"), table_name="verification_codes")
    op.drop_table("verification_codes")
    op.drop_index(op.f("ix_trusted_devices_user_id"), table_name="trusted_devices")
    op.drop_index(op.f("ix_trusted_devices_telegram_id"), table_name="trusted_devices")
    op.drop_index(op.f("ix_trusted_devices_store_id"), table_name="trusted_devices")
    op.drop_index(op.f("ix_trusted_devices_expires_at"), table_name="trusted_devices")
    op.drop_table("trusted_devices")
    op.drop_index(op.f("ix_tickets_user_id"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_store_id"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_status"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_priority"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_number"), table_name="tickets")
    op.drop_table("tickets")
    op.drop_index(op.f("ix_telegram_login_sessions_store_id"), table_name="telegram_login_sessions")
    op.drop_index(op.f("ix_telegram_login_sessions_status"), table_name="telegram_login_sessions")
    op.drop_index(op.f("ix_telegram_login_sessions_expires_at"), table_name="telegram_login_sessions")
    op.drop_index(op.f("ix_telegram_login_sessions_device_key_hash"), table_name="telegram_login_sessions")
    op.drop_table("telegram_login_sessions")
    op.drop_table("telegram_event_destinations")
    op.drop_index(op.f("ix_store_products_store_id"), table_name="store_products")
    op.drop_index(op.f("ix_store_products_product_id"), table_name="store_products")
    op.drop_table("store_products")
    op.drop_index(op.f("ix_store_payment_configurations_store_id"), table_name="store_payment_configurations")
    op.drop_table("store_payment_configurations")
    op.drop_index(op.f("ix_store_memberships_user_id"), table_name="store_memberships")
    op.drop_index(op.f("ix_store_memberships_store_id"), table_name="store_memberships")
    op.drop_table("store_memberships")
    op.drop_index(op.f("ix_store_bundles_store_id"), table_name="store_bundles")
    op.drop_index(op.f("ix_store_bundles_bundle_id"), table_name="store_bundles")
    op.drop_table("store_bundles")
    op.drop_index(op.f("ix_store_bundle_prices_store_id"), table_name="store_bundle_prices")
    op.drop_index(op.f("ix_store_bundle_prices_product_id"), table_name="store_bundle_prices")
    op.drop_index(op.f("ix_store_bundle_prices_bundle_id"), table_name="store_bundle_prices")
    op.drop_table("store_bundle_prices")
    op.drop_index(op.f("ix_reseller_profiles_user_id"), table_name="reseller_profiles")
    op.drop_table("reseller_profiles")
    op.drop_index(
        "uq_reseller_application_pending_user_store", table_name="reseller_applications", postgresql_where=sa.text("status = 'pending'")
    )
    op.drop_index(
        "uq_reseller_application_pending_domain", table_name="reseller_applications", postgresql_where=sa.text("status = 'pending'")
    )
    op.drop_index("uq_reseller_application_pending_bot", table_name="reseller_applications", postgresql_where=sa.text("status = 'pending'"))
    op.drop_index(op.f("ix_reseller_applications_user_id"), table_name="reseller_applications")
    op.drop_index(op.f("ix_reseller_applications_target_store_id"), table_name="reseller_applications")
    op.drop_table("reseller_applications")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_referral_relationships_store_id"), table_name="referral_relationships")
    op.drop_index(op.f("ix_referral_relationships_referrer_user_id"), table_name="referral_relationships")
    op.drop_table("referral_relationships")
    op.drop_index("uq_panel_admins_panel_username", table_name="panel_admins")
    op.drop_index(op.f("ix_panel_admins_store_id"), table_name="panel_admins")
    op.drop_index(op.f("ix_panel_admins_status"), table_name="panel_admins")
    op.drop_index(op.f("ix_panel_admins_panel_id"), table_name="panel_admins")
    op.drop_table("panel_admins")
    op.drop_index(
        "uq_panel_admin_request_one_pending",
        table_name="panel_admin_change_requests",
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.drop_index(op.f("ix_panel_admin_change_requests_store_id"), table_name="panel_admin_change_requests")
    op.drop_index(op.f("ix_panel_admin_change_requests_status"), table_name="panel_admin_change_requests")
    op.drop_table("panel_admin_change_requests")
    op.drop_index(op.f("ix_orders_user_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_store_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_product_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_loyalty_tiers_store_id"), table_name="loyalty_tiers")
    op.drop_table("loyalty_tiers")
    op.drop_index(op.f("ix_loyalty_rewards_store_id"), table_name="loyalty_rewards")
    op.drop_table("loyalty_rewards")
    op.drop_index(op.f("ix_loyalty_programs_store_id"), table_name="loyalty_programs")
    op.drop_table("loyalty_programs")
    op.drop_index(op.f("ix_loyalty_accounts_user_id"), table_name="loyalty_accounts")
    op.drop_index(op.f("ix_loyalty_accounts_store_id"), table_name="loyalty_accounts")
    op.drop_table("loyalty_accounts")
    op.drop_index(op.f("ix_ledger_transactions_store_id"), table_name="ledger_transactions")
    op.drop_index(op.f("ix_ledger_transactions_payment_id"), table_name="ledger_transactions")
    op.drop_index(op.f("ix_ledger_transactions_order_id"), table_name="ledger_transactions")
    op.drop_index(op.f("ix_ledger_transactions_kind"), table_name="ledger_transactions")
    op.drop_table("ledger_transactions")
    op.drop_index(op.f("ix_file_objects_owner_user_id"), table_name="file_objects")
    op.drop_table("file_objects")
    op.drop_index(op.f("ix_coupons_store_id"), table_name="coupons")
    op.drop_index(op.f("ix_coupons_code"), table_name="coupons")
    op.drop_table("coupons")
    op.drop_index(
        "uq_commission_rules_store_kind_default",
        table_name="commission_rules",
        postgresql_where=sa.text("product_id IS NULL"),
        sqlite_where=sa.text("product_id IS NULL"),
    )
    op.drop_index(op.f("ix_commission_rules_store_id"), table_name="commission_rules")
    op.drop_table("commission_rules")
    op.drop_index(op.f("ix_commission_clawbacks_referrer_user_id"), table_name="commission_clawbacks")
    op.drop_table("commission_clawbacks")
    op.drop_index(op.f("ix_bulk_operations_store_id"), table_name="bulk_operations")
    op.drop_index("ix_bulk_operations_status_created", table_name="bulk_operations")
    op.drop_index(op.f("ix_bulk_operations_status"), table_name="bulk_operations")
    op.drop_index(op.f("ix_bulk_operations_panel_id"), table_name="bulk_operations")
    op.drop_table("bulk_operations")
    op.drop_index(op.f("ix_broadcasts_store_id"), table_name="broadcasts")
    op.drop_index(op.f("ix_broadcasts_sender_user_id"), table_name="broadcasts")
    op.drop_table("broadcasts")
    op.drop_index(op.f("ix_bot_store_bindings_store_id"), table_name="bot_store_bindings")
    op.drop_index(op.f("ix_bot_store_bindings_owner_user_id"), table_name="bot_store_bindings")
    op.drop_table("bot_store_bindings")
    op.drop_index(op.f("ix_bank_sms_sources_store_id"), table_name="bank_sms_sources")
    op.drop_table("bank_sms_sources")
    op.drop_index(op.f("ix_api_credentials_store_id"), table_name="api_credentials")
    op.drop_index(op.f("ix_api_credentials_key_prefix"), table_name="api_credentials")
    op.drop_table("api_credentials")
    op.drop_index(op.f("ix_account_link_operations_user_id"), table_name="account_link_operations")
    op.drop_index(op.f("ix_account_link_operations_status"), table_name="account_link_operations")
    op.drop_index(op.f("ix_account_link_operations_person_id"), table_name="account_link_operations")
    op.drop_index(op.f("ix_account_link_operations_expires_at"), table_name="account_link_operations")
    op.drop_table("account_link_operations")
    op.drop_index(op.f("ix_terms_acceptances_user_id"), table_name="terms_acceptances")
    op.drop_table("terms_acceptances")
    op.drop_index(op.f("ix_stores_parent_store_id"), table_name="stores")
    op.drop_index(op.f("ix_stores_owner_user_id"), table_name="stores")
    op.drop_index(op.f("ix_stores_kind"), table_name="stores")
    op.drop_table("stores")
    op.drop_index(op.f("ix_product_templates_product_id"), table_name="product_templates")
    op.drop_index(op.f("ix_product_templates_panel_id"), table_name="product_templates")
    op.drop_table("product_templates")
    op.drop_index(op.f("ix_identity_link_reviews_status"), table_name="identity_link_reviews")
    op.drop_index(op.f("ix_identity_link_reviews_email"), table_name="identity_link_reviews")
    op.drop_table("identity_link_reviews")
    op.drop_index(
        "uq_identities_one_active_telegram_per_person",
        table_name="identities",
        postgresql_where=sa.text("provider = 'telegram' AND status = 'active'"),
        sqlite_where=sa.text("provider = 'telegram' AND status = 'active'"),
    )
    op.drop_index(op.f("ix_identities_user_id"), table_name="identities")
    op.drop_index(op.f("ix_identities_person_id"), table_name="identities")
    op.drop_table("identities")
    op.drop_index(op.f("ix_bundle_products_product_id"), table_name="bundle_products")
    op.drop_index(op.f("ix_bundle_products_bundle_id"), table_name="bundle_products")
    op.drop_table("bundle_products")
    op.drop_index(op.f("ix_admin_invites_user_id"), table_name="admin_invites")
    op.drop_index(op.f("ix_admin_invites_expires_at"), table_name="admin_invites")
    op.drop_table("admin_invites")
    op.drop_index(op.f("ix_account_consolidation_operations_target_person_id"), table_name="account_consolidation_operations")
    op.drop_index(op.f("ix_account_consolidation_operations_status"), table_name="account_consolidation_operations")
    op.drop_table("account_consolidation_operations")
    op.drop_index(op.f("ix_users_person_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_servers_panel_id"), table_name="servers")
    op.drop_table("servers")
    op.drop_index(op.f("ix_products_default_bundle_id"), table_name="products")
    op.drop_index(op.f("ix_products_category"), table_name="products")
    op.drop_table("products")
    op.drop_index(op.f("ix_panel_orphans_status"), table_name="panel_orphans")
    op.drop_index(op.f("ix_panel_orphans_panel_id"), table_name="panel_orphans")
    op.drop_table("panel_orphans")
    op.drop_index(op.f("ix_panel_nodes_status"), table_name="panel_nodes")
    op.drop_index(op.f("ix_panel_nodes_panel_id"), table_name="panel_nodes")
    op.drop_table("panel_nodes")
    op.drop_index(op.f("ix_bundle_members_panel_id"), table_name="bundle_members")
    op.drop_index(op.f("ix_bundle_members_bundle_id"), table_name="bundle_members")
    op.drop_table("bundle_members")
    op.drop_index(op.f("ix_account_link_audits_person_id"), table_name="account_link_audits")
    op.drop_index(op.f("ix_account_link_audits_operation_id"), table_name="account_link_audits")
    op.drop_index(op.f("ix_account_link_audits_action"), table_name="account_link_audits")
    op.drop_table("account_link_audits")
    op.drop_table("system_settings")
    op.drop_index(op.f("ix_security_events_kind"), table_name="security_events")
    op.drop_table("security_events")
    op.drop_index(op.f("ix_persons_status"), table_name="persons")
    op.drop_table("persons")
    op.drop_table("panels")
    op.drop_index(op.f("ix_outbox_events_topic"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_status"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_available_at"), table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("feature_flags")
    op.drop_table("bundles")
    op.drop_index(op.f("ix_backup_runs_target"), table_name="backup_runs")
    op.drop_table("backup_runs")
    op.drop_index(op.f("ix_audit_events_store_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_entity_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_action"), table_name="audit_events")
    op.drop_table("audit_events")

    if op.get_bind().dialect.name == "postgresql":
        for seq in _SEQUENCES:
            op.execute(f"DROP SEQUENCE IF EXISTS {seq}")
