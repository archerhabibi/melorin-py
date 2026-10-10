import datetime as dt
import uuid

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.core.db import Base, CreatedMixin, IdMixin, TimestampMixin


class Notification(IdMixin, CreatedMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"))
    kind: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    dedup_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    telegram_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|sent|failed|skipped
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramEventDestination(IdMixin, TimestampMixin, Base):
    """Event Center: one group per Admin (store_id NULL) and per Reseller store, with forum topics."""

    __tablename__ = "telegram_event_destinations"
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"), unique=True)
    chat_id: Mapped[str] = mapped_column(String(50))
    topics: Mapped[dict | None] = mapped_column(JSON)  # {"payments": thread_id, "orders": ..., ...}
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)
