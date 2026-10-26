import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Priority = Literal["low", "normal", "high", "urgent"]
Status = Literal["open", "answered", "closed"]


class _NeedsTextOrImage(BaseModel):
    """A message needs text, an attached image, or both."""

    @model_validator(mode="after")
    def _text_or_image(self):
        if not self.body and not self.attachment_id:
            raise ValueError("متن یا تصویر پیوست لازم است.")
        return self


class CreateTicket(_NeedsTextOrImage):
    subject: str = Field(min_length=2, max_length=200)
    body: str = Field(default="", max_length=10_000)
    attachment_id: uuid.UUID | None = None  # an image uploaded through POST /stores/{id}/tickets/attachments
    # Customers may flag a ticket as important; "urgent" is reserved for staff triage.
    priority: Literal["low", "normal", "high"] = "normal"
    department: str | None = Field(default=None, max_length=50)


class AddMessage(_NeedsTextOrImage):
    body: str = Field(default="", max_length=10_000)
    attachment_id: uuid.UUID | None = None


class EditMessage(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class UpdateTicket(BaseModel):
    """Customer-side edit: rename the ticket, change its priority, close or re-open it."""

    subject: str | None = Field(default=None, min_length=2, max_length=200)
    priority: Literal["low", "normal", "high"] | None = None
    status: Literal["open", "closed"] | None = None


class AdminUpdateTicket(BaseModel):
    subject: str | None = Field(default=None, min_length=2, max_length=200)
    status: Status | None = None
    priority: Priority | None = None
    department: str | None = Field(default=None, max_length=50)


class AdminAddMessage(_NeedsTextOrImage):
    body: str = Field(default="", max_length=10_000)
    attachment_id: uuid.UUID | None = None
    internal: bool = False  # staff-only note: stored, but hidden from the customer and no notification
    status: Status | None = None  # optionally move the ticket in the same step (e.g. answer + close)


class TicketOut(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    number: str | None = None  # 6-char short code; None on pre-migration rows
    subject: str
    status: str
    priority: str = "normal"
    department: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class TicketMessageOut(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    is_staff: bool
    is_internal: bool = False
    body: str
    created_at: dt.datetime
    edited_at: dt.datetime | None = None
    attachment_id: uuid.UUID | None = None  # image: GET .../messages/{id}/attachment


class AttachmentOut(BaseModel):
    id: uuid.UUID
    content_type: str
    size: int
