import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.core.db import Base, CreatedMixin, IdMixin, TimestampMixin

TICKET_STATUSES = ("open", "answered", "closed")
TICKET_PRIORITIES = ("low", "normal", "high", "urgent")


class Ticket(IdMixin, TimestampMixin, Base):
    __tablename__ = "tickets"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    number: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open|answered|closed
    priority: Mapped[str] = mapped_column(String(10), default="normal", server_default="normal", index=True)  # low|normal|high|urgent
    department: Mapped[str | None] = mapped_column(String(50))  # free-form category (billing, technical, ...)


class TicketMessage(IdMixin, CreatedMixin, Base):
    __tablename__ = "ticket_messages"
    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tickets.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # staff-only note, never shown to the customer
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("file_objects.id"))
