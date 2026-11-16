import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class GoogleLinkIn(BaseModel):
    id_token: str = Field(min_length=20, max_length=4000)


class EmailStartIn(BaseModel):
    email: EmailStr


class EmailConfirmIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)


class ConfirmIn(BaseModel):
    operation_id: uuid.UUID
    keep_telegram: Literal["target", "source"] | None = None  # only needed when both profiles own an active Telegram


class RejectIn(BaseModel):
    operation_id: uuid.UUID


class UnlinkIn(BaseModel):
    identity_id: uuid.UUID
    current_password: str | None = Field(default=None, max_length=128)  # required when the account has a password (re-authentication)
    reauth_code: str | None = Field(default=None, min_length=4, max_length=12)  # e-mail one-time code for passwordless accounts


class ConsolidationIn(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")


class ReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class TelegramStartOut(BaseModel):
    operation_id: uuid.UUID
    code: str
    expires_in: int
    replace: bool
    telegram_deeplink: str | None = None
