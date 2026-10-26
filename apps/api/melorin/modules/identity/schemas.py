import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: uuid.UUID
    is_admin: bool
    # Where Core bound this session (informational: Core never trusts the client to say it, see core/channel.py).
    channel: str | None = None
    store_id: uuid.UUID | None = None


class EmailCodeRequest(BaseModel):
    email: EmailStr


class EmailCodeVerify(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)
    referral_code: str | None = None
    accept_terms_version: str | None = None


class PasswordLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    totp_code: str | None = None


class SetPassword(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class AdminPasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class GoogleLogin(BaseModel):
    id_token: str
    totp_code: str | None = None  # required when the matched account is a super admin


class WebHandoffIn(BaseModel):
    store_id: uuid.UUID | None = None


class WebHandoffOut(BaseModel):
    url: str
    google_linked: bool


class WebHandoffRedeem(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class GoogleLink(BaseModel):
    id_token: str


class TelegramProfile(BaseModel):
    telegram_id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


class TelegramBotLogin(TelegramProfile):
    store_id: uuid.UUID | None = None
    referral_code: str | None = None


class TelegramWebAppLogin(BaseModel):
    init_data: str
    store_id: uuid.UUID | None = None


class TelegramLink(TelegramProfile):
    code: str
    store_id: uuid.UUID | None = None  # the store of the bot that sends it (omitted = main bot)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class IdentityOut(BaseModel):
    id: uuid.UUID
    provider: str
    subject: str
    verified: bool


class MeOut(BaseModel):
    id: uuid.UUID
    display_name: str | None
    email: str | None
    is_admin: bool
    is_guest: bool
    totp_enabled: bool
    referral_code: str
    identities: list[IdentityOut]


class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    locale: str | None = Field(default=None, max_length=8)


class LinkCodeOut(BaseModel):
    code: str
    expires_in: int
    telegram_deeplink: str | None = None


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_url: str


class TotpEnable(BaseModel):
    code: str


# ---------------- website login approved in the Telegram bot ----------------
class TelegramWebStart(BaseModel):
    store_id: uuid.UUID | None = None
    device_key: str | None = Field(default=None, max_length=128)  # non-browser clients only; browsers use the HttpOnly cookie
    remember: bool = True  # the visitor lets this browser be trusted after a manual approval


class TelegramWebStartOut(BaseModel):
    session_id: str
    poll_token: str  # shown once; only its hash is stored
    deeplink: str
    qr: str | None = None  # data:image/svg+xml URI of the deep link
    match_code: str | None = None  # None when number matching is disabled or the browser is already trusted
    bot_username: str
    expires_in: int
    poll_interval: int
    level: Literal["silent", "auto", "manual"] = "manual"  # automatic verification level decided for this browser


class TelegramWebPoll(BaseModel):
    poll_token: str = Field(min_length=20, max_length=128)


class TelegramWebPollOut(BaseModel):
    status: str  # pending | scanned | approved | denied | expired | consumed
    reason: str | None = None
    expires_in: int = 0
    tokens: TokenPair | None = None
    # Present only when an ``auto`` request had to fall back to the manual number match (the browser shows the number then).
    level: Literal["silent", "auto", "manual"] | None = None
    match_code: str | None = None


class TelegramWebInspect(TelegramProfile):
    session_id: str = Field(min_length=8, max_length=32)
    store_id: uuid.UUID


class TelegramWebInspectOut(BaseModel):
    status: str
    device: str
    ip: str | None
    age_seconds: int
    expires_in: int
    number_match: bool
    choices: list[str]
    auto_approved: bool = False  # trusted browser: opening the link was the whole approval, nothing to tap
    auto_reason: str | None = None  # when auto_approved is False for a trusted-device attempt: why it fell back / was refused


class TelegramWebDecision(TelegramProfile):
    session_id: str = Field(min_length=8, max_length=32)
    store_id: uuid.UUID
    action: Literal["approve", "deny"]
    choice: str | None = Field(default=None, max_length=8)


class TelegramWebDecisionOut(BaseModel):
    result: Literal["approved", "denied", "retry"]
    reason: str | None = None
    remaining: int | None = None
    choices: list[str] = []


class TelegramWebForget(BaseModel):
    device_key: str | None = Field(default=None, max_length=128)  # normally the HttpOnly cookie is used instead


class TelegramWebDeviceOut(BaseModel):
    id: str
    label: str | None = None
    last_ip: str | None = None
    uses: int = 0
    last_seen_ago_seconds: int = 0
    expires_in_seconds: int = 0


class TelegramWebDevices(TelegramProfile):
    store_id: uuid.UUID


class TelegramWebDevicesOut(BaseModel):
    devices: list[TelegramWebDeviceOut]


class TelegramWebRevoke(TelegramProfile):
    store_id: uuid.UUID
    device_id: str | None = Field(default=None, max_length=36)  # None = every device of this Telegram account ("not me")


class TelegramWebRevokeOut(BaseModel):
    revoked: int
