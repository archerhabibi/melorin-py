import datetime as dt
import uuid

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.core.db import Base, CreatedMixin, IdMixin, TimestampMixin, utcnow


class WebhookEndpoint(IdMixin, TimestampMixin, Base):
    """Outgoing webhook endpoint of a store (v1.1). Secret encrypted at rest, shown once at creation/rotation."""

    __tablename__ = "webhook_endpoints"
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(String(200))
    events: Mapped[list] = mapped_column(JSON, default=list)  # [] or ["*"] = all supported
    secret_enc: Mapped[str] = mapped_column(Text)
    previous_secret_enc: Mapped[str | None] = mapped_column(Text)  # dual-sign window after rotation
    previous_secret_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | disabled | auto_disabled
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class WebhookDelivery(IdMixin, TimestampMixin, Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("endpoint_id", "event_id"),)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("webhook_endpoints.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    event_id: Mapped[str] = mapped_column(String(64))  # stable id, receivers dedupe on it
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending | delivering | delivered | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_response_ms: Mapped[int | None] = mapped_column(Integer)
    delivered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
