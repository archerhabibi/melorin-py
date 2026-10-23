import datetime as dt
import uuid

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin


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
    # Connection health shown in the panels (migration 0031). ``last_error`` is cleared by the next successful send.
    last_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    last_error_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Broadcast(IdMixin, CreatedMixin, Base):
    """پیام همگانی: one message an admin or a reseller sent to an audience; the per-person delivery rides on ``notifications``
    (``dedup_key`` = ``bc:<broadcast>:<user>:<store>``), so a retry can never send twice."""

    __tablename__ = "broadcasts"
    sender_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)  # the sender's own store (main or reseller)
    audience: Mapped[str] = mapped_column(String(30))  # all_own | resellers | customers | everyone
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    recipients: Mapped[int] = mapped_column(Integer, default=0)
