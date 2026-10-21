import datetime as dt
import uuid

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin, utcnow


class AuditEvent(IdMixin, CreatedMixin, Base):
    """Append-only (enforced by DB trigger on PostgreSQL)."""

    __tablename__ = "audit_events"
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    actor_type: Mapped[str] = mapped_column(String(20))  # user | admin | reseller | system | api
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    data: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))


class SecurityEvent(IdMixin, CreatedMixin, Base):
    __tablename__ = "security_events"
    kind: Mapped[str] = mapped_column(String(50), index=True)  # login_failed | cross_store | brute_force ...
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    ip: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict | None] = mapped_column(JSON)


class OutboxEvent(IdMixin, CreatedMixin, Base):
    __tablename__ = "outbox_events"
    topic: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    dedup_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64))


class FeatureFlag(IdMixin, TimestampMixin, Base):
    """Emergency controls & maintenance. A disabled flag in any matching scope blocks the feature."""

    __tablename__ = "feature_flags"
    __table_args__ = (UniqueConstraint("key", "scope_type", "scope_id"),)
    key: Mapped[str] = mapped_column(String(50))  # purchase|payment|provisioning|reseller_sales|api|bot|test_account|maintenance
    scope_type: Mapped[str] = mapped_column(String(20), default="global")  # global | store | channel
    scope_id: Mapped[str] = mapped_column(String(64), default="*")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(500))


class SystemSetting(IdMixin, TimestampMixin, Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class FileObject(IdMixin, CreatedMixin, Base):
    __tablename__ = "file_objects"
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"))
    purpose: Mapped[str] = mapped_column(String(30))  # receipt | ticket
    storage_key: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))


class TestAccountGrant(IdMixin, CreatedMixin, Base):
    __tablename__ = "test_account_grants"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"))
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"))
    identity_keys: Mapped[list | None] = mapped_column(JSON)


class BackupRun(IdMixin, CreatedMixin, Base):
    __tablename__ = "backup_runs"
    status: Mapped[str] = mapped_column(String(20))
    location: Mapped[str | None] = mapped_column(String(300))
    size: Mapped[int | None] = mapped_column(BigInteger)
    details: Mapped[str | None] = mapped_column(Text)
