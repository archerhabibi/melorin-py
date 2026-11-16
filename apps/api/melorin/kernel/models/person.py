"""Person: the one real human behind several accounts and login methods (docs/07-DOMAIN-DATA-MODEL.md).

Vocabulary mapping onto the existing schema (nothing was renamed, no id changed):

* **Person**  - new. Owns the profile, the consolidation history and (after consolidation) the *central* account whose wallet is used.
* **Account** - the existing ``users`` row: orders, wallets, VPN accounts and payments keep pointing at it.
* **Login Identity** - the existing ``identities`` row (telegram | google | email), now carrying ``person_id`` and a lifecycle ``status``.

Linking identities and consolidating money are separate use cases and have separate tables.
"""

import datetime as dt
import secrets
import uuid

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin


def _public_id() -> str:
    return "p_" + secrets.token_urlsafe(12)


class Person(IdMixin, TimestampMixin, Base):
    __tablename__ = "persons"
    public_id: Mapped[str] = mapped_column(String(32), unique=True, default=_public_id)  # unguessable, safe to show
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)  # active | restricted | blocked | merged
    # The account whose wallet serves the whole person once a consolidation completed (NULL = wallets are still per account).
    central_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid
    )  # plain column on purpose: users.person_id already points the other way (no FK cycle)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))


class AccountLinkOperation(IdMixin, TimestampMixin, Base):
    """One attempt to attach / detach / replace a login identity. The token (when there is one) is stored only as a SHA-256."""

    __tablename__ = "account_link_operations"
    person_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("persons.id"), index=True)  # destination person
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)  # the signed-in account that asked
    provider: Mapped[str] = mapped_column(String(20))  # telegram | google | email
    operation_type: Mapped[str] = mapped_column(String(12))  # link | unlink | replace | merge
    # candidate | pending_verification | confirmed | conflict | rejected | revoked | expired (docs/25 §3)
    status: Mapped[str] = mapped_column(String(24), default="pending_verification", index=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    subject_ref: Mapped[str | None] = mapped_column(String(320))  # provider subject being attached (telegram id / google sub / email)
    conflict_person_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict | None] = mapped_column(JSON)


class AccountLinkEvidence(IdMixin, CreatedMixin, Base):
    """What proved ownership. Never holds a raw OAuth token, password or one-time code."""

    __tablename__ = "account_link_evidence"
    operation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("account_link_operations.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32))  # session | oauth_google | email_code | telegram_bot | link_token | admin_review
    subject_reference: Mapped[str | None] = mapped_column(String(320))
    result: Mapped[str] = mapped_column(String(12))  # passed | failed
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict | None] = mapped_column(JSON)


class AccountConsolidationOperation(IdMixin, TimestampMixin, Base):
    """Moving money between the wallets of one person's accounts. Independent of identity linking (docs/25 §5)."""

    __tablename__ = "account_consolidation_operations"
    target_person_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("persons.id"), index=True)
    central_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))  # the account that keeps the wallets
    source_user_ids: Mapped[list] = mapped_column(JSON, default=list)
    # preflight_failed | blocked | pending_approval | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending_approval", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    preflight: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(500))


class WalletTransfer(IdMixin, CreatedMixin, Base):
    __tablename__ = "wallet_transfers"
    consolidation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("account_consolidation_operations.id"), index=True)
    source_wallet_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("wallets.id"), index=True)
    target_wallet_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("wallets.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8))
    ledger_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ledger_transactions.id"))
    status: Mapped[str] = mapped_column(String(12), default="done")


class AccountLinkAudit(IdMixin, CreatedMixin, Base):
    """Append-only history of linking, conflicts, replacements and consolidation. Updating or deleting a row is refused."""

    __tablename__ = "account_link_audits"
    person_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"), index=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_type: Mapped[str] = mapped_column(String(12), default="user")  # user | admin | system | bot
    operation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(500))


@event.listens_for(AccountLinkAudit, "before_update")
@event.listens_for(AccountLinkAudit, "before_delete")
def _audit_is_append_only(mapper, connection, target):  # noqa: ARG001
    raise PermissionError("account_link_audits is append-only")


# ----------------------------------------------------------------------------------------------------------------------
# Every account has a person and every identity names it, whichever code path created the row (service, CLI, admin invite, tests).
# The hooks run inside the flush, in the same transaction, with the flush's own connection.
# ----------------------------------------------------------------------------------------------------------------------
from typing import cast  # noqa: E402

from sqlalchemy import Table, insert, select  # noqa: E402

from melorin.kernel.base import utcnow  # noqa: E402
from melorin.kernel.models.identity import Identity, User  # noqa: E402


@event.listens_for(User, "before_insert")
def _user_gets_person(mapper, connection, target):  # noqa: ARG001
    if target.person_id is not None:
        return
    pid, now = uuid.uuid4(), utcnow()
    connection.execute(
        insert(cast(Table, Person.__table__)).values(id=pid, public_id=_public_id(), status="active", created_at=now, updated_at=now)
    )
    target.person_id = pid


@event.listens_for(Identity, "before_insert")
def _identity_names_person(mapper, connection, target):  # noqa: ARG001
    if target.person_id is not None:
        return
    target.person_id = connection.execute(select(User.__table__.c.person_id).where(User.__table__.c.id == target.user_id)).scalar()
    if target.status is None:
        target.status = "active"
