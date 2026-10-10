import uuid

from pydantic import BaseModel, EmailStr, Field


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: uuid.UUID
    is_admin: bool


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


class GoogleLogin(BaseModel):
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
