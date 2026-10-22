"""Request bodies of the admin integrations API (unchanged from the former single module)."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from melorin.core import integrations


class EmailIn(BaseModel):
    enabled: bool
    host: str = Field("", max_length=253)
    port: int = Field(587, ge=1, le=65535)
    username: str = Field("", max_length=200)
    password: str | None = Field(None, max_length=500)  # None keeps the stored password, "" clears it
    from_addr: str = Field("", max_length=254)
    security: Literal["starttls", "ssl", "none"] = "starttls"


class AdminAccessIn(BaseModel):
    enabled: bool
    ips: list[str] = Field(default_factory=list, max_length=50)


class GoogleIn(BaseModel):
    enabled: bool
    client_id: str = Field("", max_length=200)
    admin_login: bool = True
    store_login: bool = True


class TelegramIn(BaseModel):
    enabled: bool
    store_login: bool = True
    bot_login: bool = True
    number_match: bool = True
    ttl_seconds: int = Field(180, ge=integrations.TELEGRAM_TTL_MIN, le=integrations.TELEGRAM_TTL_MAX)
    oidc_login: bool = False
    client_id: str = Field("", max_length=30)
    client_secret: str | None = Field(None, max_length=200)  # None keeps the stored secret, "" clears it


class MainBotIn(BaseModel):
    username: str | None = Field(None, max_length=100)  # None / "" -> detect it from the bot token via getMe


class EmailTestIn(BaseModel):
    to: EmailStr


class BackupS3In(BaseModel):
    enabled: bool
    endpoint: str = Field("", max_length=300)
    region: str = Field("", max_length=60)
    bucket: str = Field("", max_length=100)
    prefix: str = Field("melorin", max_length=200)
    access_key: str = Field("", max_length=200)
    secret_key: str | None = Field(None, max_length=500)  # None keeps, "" clears
