"""Person / Account / Login-Identity linking (docs/25-Person-Account-Linking-Design.md).

* ``persons`` + ``users.person_id``: every existing account gets its OWN person (nothing is merged because of a shared e-mail, name or
  device; accounts that belong together are linked later by their owner, with proof).
* ``identities``: ``person_id``, ``status`` (active|revoked), ``revoked_at``, ``last_used_at``. Duplicate active Telegram identities of one
  account (possible before this rule) keep the oldest and revoke the rest, then ``uq_identities_one_active_telegram_per_person`` is created.
* ``wallets``: ``status`` (active|consolidated) and ``consolidated_into_id``.
* New tables: ``account_link_operations``, ``account_link_evidence``, ``account_consolidation_operations``, ``wallet_transfers``,
  ``account_link_audits`` (append-only, enforced by a database trigger).

No balance is touched. Forward-compatible: the old columns keep their meaning.
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0057_person_account_linking"
down_revision = "0056_main_store_payment_config"
branch_labels = None
depends_on = None

_NOW = sa.func.now()


def _ts(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=_NOW, nullable=False)


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column("central_user_id", sa.Uuid(), nullable=True),
        sa.Column("merged_into_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=True),
        _ts(),
        _ts("updated_at"),
        sa.UniqueConstraint("public_id", name="uq_persons_public_id"),
    )
    op.create_index("ix_persons_status", "persons", ["status"])

    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("person_id", sa.Uuid(), nullable=True))
        b.create_foreign_key("fk_users_person_id_persons", "persons", ["person_id"], ["id"])
        b.create_index("ix_users_person_id", ["person_id"])
    with op.batch_alter_table("identities") as b:
        b.add_column(sa.Column("person_id", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("status", sa.String(10), nullable=False, server_default="active"))
        b.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
        b.create_foreign_key("fk_identities_person_id_persons", "persons", ["person_id"], ["id"])
        b.create_index("ix_identities_person_id", ["person_id"])
    with op.batch_alter_table("wallets") as b:
        b.add_column(sa.Column("status", sa.String(12), nullable=False, server_default="active"))
        b.add_column(sa.Column("consolidated_into_id", sa.Uuid(), nullable=True))
        b.create_foreign_key("fk_wallets_consolidated_into_id_wallets", "wallets", ["consolidated_into_id"], ["id"])

    _backfill()

    op.create_index(
        "uq_identities_one_active_telegram_per_person",
        "identities",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("provider = 'telegram' AND status = 'active'"),
        sqlite_where=sa.text("provider = 'telegram' AND status = 'active'"),
    )

    op.create_table(
        "account_link_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("operation_type", sa.String(12), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("subject_ref", sa.String(320), nullable=True),
        sa.Column("conflict_person_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=True),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        _ts(),
        _ts("updated_at"),
        sa.UniqueConstraint("token_hash", name="uq_account_link_operations_token_hash"),
    )
    for col in ("person_id", "user_id", "status", "expires_at"):
        op.create_index(f"ix_account_link_operations_{col}", "account_link_operations", [col])

    op.create_table(
        "account_link_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("account_link_operations.id"), nullable=False),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("subject_reference", sa.String(320), nullable=True),
        sa.Column("result", sa.String(12), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        _ts(),
    )
    op.create_index("ix_account_link_evidence_operation_id", "account_link_evidence", ["operation_id"])

    op.create_table(
        "account_consolidation_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("target_person_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("central_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_user_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("initiated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("preflight", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        _ts(),
        _ts("updated_at"),
        sa.UniqueConstraint("idempotency_key", name="uq_account_consolidation_operations_idempotency_key"),
    )
    op.create_index("ix_account_consolidation_operations_target_person_id", "account_consolidation_operations", ["target_person_id"])
    op.create_index("ix_account_consolidation_operations_status", "account_consolidation_operations", ["status"])

    op.create_table(
        "wallet_transfers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("consolidation_id", sa.Uuid(), sa.ForeignKey("account_consolidation_operations.id"), nullable=False),
        sa.Column("source_wallet_id", sa.Uuid(), sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("target_wallet_id", sa.Uuid(), sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("ledger_transaction_id", sa.Uuid(), sa.ForeignKey("ledger_transactions.id"), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="done"),
        _ts(),
    )
    for col in ("consolidation_id", "source_wallet_id", "target_wallet_id"):
        op.create_index(f"ix_wallet_transfers_{col}", "wallet_transfers", [col])

    op.create_table(
        "account_link_audits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=True),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(12), nullable=False, server_default="user"),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        _ts(),
    )
    for col in ("person_id", "action", "operation_id"):
        op.create_index(f"ix_account_link_audits_{col}", "account_link_audits", [col])
    _append_only("account_link_audits")


def _backfill() -> None:
    bind = op.get_bind()
    users = sa.table("users", sa.column("id", sa.Uuid()), sa.column("person_id", sa.Uuid()))
    persons = sa.table("persons", sa.column("id", sa.Uuid()), sa.column("public_id", sa.String()), sa.column("status", sa.String()))
    idents = sa.table(
        "identities",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("person_id", sa.Uuid()),
        sa.column("provider", sa.String()),
        sa.column("status", sa.String()),
        sa.column("revoked_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    import secrets

    for (uid,) in bind.execute(sa.select(users.c.id).where(users.c.person_id.is_(None))).all():
        pid = uuid.uuid4()
        bind.execute(sa.insert(persons).values(id=pid, public_id="p_" + secrets.token_urlsafe(12), status="active"))
        bind.execute(sa.update(users).where(users.c.id == uid).values(person_id=pid))
    bind.execute(
        sa.update(idents)
        .values(person_id=sa.select(users.c.person_id).where(users.c.id == idents.c.user_id).scalar_subquery())
        .where(idents.c.person_id.is_(None))
    )
    # one active Telegram per person: keep the oldest of any legacy duplicates, revoke the rest (rows are kept for history)
    seen: set = set()
    rows = bind.execute(
        sa.select(idents.c.id, idents.c.person_id)
        .where(idents.c.provider == "telegram", idents.c.status == "active")
        .order_by(idents.c.created_at, idents.c.id)
    ).all()
    for iid, pid in rows:
        if pid in seen:
            bind.execute(sa.update(idents).where(idents.c.id == iid).values(status="revoked", revoked_at=sa.func.now()))
        seen.add(pid)


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


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS account_link_audits_no_change ON account_link_audits")
        op.execute("DROP FUNCTION IF EXISTS account_link_audits_append_only()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS account_link_audits_no_update")
        op.execute("DROP TRIGGER IF EXISTS account_link_audits_no_delete")
    for t in (
        "account_link_audits",
        "wallet_transfers",
        "account_consolidation_operations",
        "account_link_evidence",
        "account_link_operations",
    ):
        op.drop_table(t)
    op.drop_index("uq_identities_one_active_telegram_per_person", table_name="identities")
    with op.batch_alter_table("wallets") as b:
        b.drop_constraint("fk_wallets_consolidated_into_id_wallets", type_="foreignkey")
        b.drop_column("consolidated_into_id")
        b.drop_column("status")
    with op.batch_alter_table("identities") as b:
        b.drop_index("ix_identities_person_id")
        b.drop_constraint("fk_identities_person_id_persons", type_="foreignkey")
        for c in ("last_used_at", "revoked_at", "status", "person_id"):
            b.drop_column(c)
    with op.batch_alter_table("users") as b:
        b.drop_index("ix_users_person_id")
        b.drop_constraint("fk_users_person_id_persons", type_="foreignkey")
        b.drop_column("person_id")
    op.drop_table("persons")
