import datetime as dt
import uuid

from pydantic import BaseModel, Field


class CreateTicket(BaseModel):
    subject: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)


class AddMessage(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class TicketOut(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    number: str | None = None  # 6-char short code; None on pre-migration rows
    subject: str
    status: str
    created_at: dt.datetime
    updated_at: dt.datetime


class TicketMessageOut(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    is_staff: bool
    body: str
    created_at: dt.datetime
