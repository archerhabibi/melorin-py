import datetime as dt
import uuid

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin


class Store(IdMixin, TimestampMixin, Base):
    __tablename__ = "stores"
    kind: Mapped[str] = mapped_column(String(20), index=True)  # main | reseller
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    # Main Store has NULL; reseller stores point to the store they represent.
    # This makes multi-store reseller ownership explicit and queryable.
    parent_store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | suspended
    currency: Mapped[str] = mapped_column(String(8), default="IRT")  # per-store currency (v1.1); immutable once wallets exist
    branding: Mapped[dict | None] = mapped_column(JSON)  # logo, colors, support handle
    bot_messages: Mapped[dict | None] = mapped_column(JSON)  # customisable bot texts
    bot_token_enc: Mapped[str | None] = mapped_column(String(500))
    bot_username: Mapped[str | None] = mapped_column(String(100))
    # Public hostname the store is served from (lower-case, no scheme/port). Reseller stores must have one;
    # Main Store may leave it empty. Unique across all stores.
    domain: Mapped[str | None] = mapped_column(String(255), unique=True)
    # Telegram bot runtime (reseller stores). ``bot_enabled`` lets the admin switch the bot off without suspending the
    # store; the reseller runner reports ``bot_status`` (connecting|running|error|stopped|disabled) and the last error
    # through Core, so the admin panel shows whether the bot is really connected.
    bot_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    bot_status: Mapped[str | None] = mapped_column(String(20))
    bot_status_detail: Mapped[str | None] = mapped_column(String(300))
    bot_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class BotStoreBinding(IdMixin, TimestampMixin, Base):
    """Authoritative mapping between one Telegram bot, one Store, and its owner."""

    __tablename__ = "bot_store_bindings"
    __table_args__ = (
        UniqueConstraint("bot_key"),
        UniqueConstraint("store_id"),
    )
    bot_key: Mapped[str] = mapped_column(String(120))  # stable identity/fingerprint, never the token
    bot_username: Mapped[str | None] = mapped_column(String(100))
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    bot_kind: Mapped[str] = mapped_column(String(20), default="reseller")
    status: Mapped[str] = mapped_column(String(20), default="active")
    config: Mapped[dict | None] = mapped_column(JSON)


class StoreMembership(IdMixin, CreatedMixin, Base):
    __tablename__ = "store_memberships"
    __table_args__ = (UniqueConstraint("store_id", "user_id"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="customer")  # customer | owner
    status: Mapped[str] = mapped_column(String(20), default="active")
    note: Mapped[str | None] = mapped_column(String(500))


class ResellerProfile(IdMixin, TimestampMixin, Base):
    __tablename__ = "reseller_profiles"
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    debt_limit: Mapped[int] = mapped_column(BigInteger, default=0)
    api_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sales_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # future: parent_reseller_id for sub-resellers (not in V1)


class ResellerApplication(IdMixin, TimestampMixin, Base):
    __tablename__ = "reseller_applications"
    __table_args__ = (
        Index(
            "uq_reseller_application_pending_user_store",
            "user_id",
            "target_store_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("uq_reseller_application_pending_domain", "domain", unique=True, postgresql_where=text("status = 'pending'")),
        Index("uq_reseller_application_pending_bot", "bot_key", unique=True, postgresql_where=text("status = 'pending'")),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_name: Mapped[str] = mapped_column(String(200))
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|awaiting_details|approved|rejected|cancelled
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    target_store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"))
    # Requested store hostname and the reseller's Telegram bot. The token is stored encrypted and is never
    # returned by any endpoint; bot_key is the stable "tg:<bot id>" identity used for uniqueness checks.
    domain: Mapped[str | None] = mapped_column(String(255))
    bot_token_enc: Mapped[str | None] = mapped_column(String(500))
    bot_key: Mapped[str | None] = mapped_column(String(120))
    bot_username: Mapped[str | None] = mapped_column(String(100))
    bot_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(String(500))
    # Two-step flow (Telegram): an application may be filed without domain/bot. When the admin approves such a
    # request it moves to ``awaiting_details`` and keeps the approved debt limit here until the applicant
    # supplies the domain and bot token; only then is the store created.
    approved_debt_limit: Mapped[int | None] = mapped_column(BigInteger)
    # Automatic identity verification (docs/21): proof that the applicant controls the domain, retried by a worker job.
    domain_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    domain_method: Mapped[str | None] = mapped_column(String(10))  # dns | http
    verify_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    verify_next_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    verify_error: Mapped[str | None] = mapped_column(String(200))
    # Automatic approval and continuous re-verification of the approved store (docs/21).
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    recheck_next_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    recheck_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    recheck_error: Mapped[str | None] = mapped_column(String(200))
    identity_lost_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ApiCredential(IdMixin, TimestampMixin, Base):
    """Reseller API key. Raw secret is shown once; only its SHA-256 is stored.

    Lifecycle: create (active or inactive) -> activate / disable -> rotate (new key, old revoked) -> revoke (terminal).
    """

    __tablename__ = "api_credentials"
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")  # inactive|active|disabled|revoked
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=120)
    ip_allowlist: Mapped[list | None] = mapped_column(JSON)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class StorePaymentConfiguration(IdMixin, TimestampMixin, Base):
    """Per-store payment destination (v1.1): a reseller store's top-ups go to that seller's own account/gateway."""

    __tablename__ = "store_payment_configurations"
    __table_args__ = (UniqueConstraint("store_id", "provider"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))  # manual_card | zarinpal | ...
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    public_config: Mapped[dict | None] = mapped_column(JSON)  # card_number, holder, bank, min/max amount
    secret_enc: Mapped[str | None] = mapped_column(Text)  # encrypted JSON (merchant_id, api keys)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class AdminTask(IdMixin, TimestampMixin, Base):
    """A manual step only a human admin can do outside Melorin (a Google console or BotFather setting, DNS ...).

    Created when a reseller applies / their domain is known; the admin ticks it done in the panel. One row per
    (kind, application): re-running the onboarding never duplicates a task.
    """

    __tablename__ = "admin_tasks"
    __table_args__ = (UniqueConstraint("kind", "application_id", name="uq_admin_tasks_kind_application"),)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # review_application | google_origin | telegram_login | dns_tls
    application_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("reseller_applications.id"), index=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open | done
    done_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    done_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
