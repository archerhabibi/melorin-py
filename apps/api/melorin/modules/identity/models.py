import datetime as dt
import secrets
import uuid

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from melorin.core.db import Base, CreatedMixin, IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    display_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), unique=True)  # verified primary email (platform-unique)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_roles: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)
    locale: Mapped[str] = mapped_column(String(8), default="fa")
    referral_code: Mapped[str] = mapped_column(String(16), unique=True, default=lambda: secrets.token_hex(5))
    totp_secret_enc: Mapped[str | None] = mapped_column(String(500))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_last_counter: Mapped[int | None] = mapped_column()
    allowed_ips: Mapped[list | None] = mapped_column(JSON)  # optional admin IP restriction
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    identities: Mapped[list["Identity"]] = relationship(back_populates="user", lazy="selectin")


class Identity(IdMixin, CreatedMixin, Base):
    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20))  # telegram | google | email
    subject: Mapped[str] = mapped_column(String(320))
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict | None] = mapped_column(JSON)
    user: Mapped[User] = relationship(back_populates="identities")


class RefreshToken(IdMixin, CreatedMixin, Base):
    __tablename__ = "refresh_tokens"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    # Channel binding (docs/16): the channel/store this session family was opened for. Rotation re-issues exactly this,
    # so a refresh token can never move a session to another store. NULL = legacy row: refused at rotation (re-login).
    channel: Mapped[str | None] = mapped_column(String(10))
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"))


class VerificationCode(IdMixin, CreatedMixin, Base):
    """One-time codes: email login/verify and Telegram account linking."""

    __tablename__ = "verification_codes"
    purpose: Mapped[str] = mapped_column(String(30), index=True)  # email_login | telegram_link
    target: Mapped[str] = mapped_column(String(320), index=True)  # email address or user id
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"))  # handoff: the store it was minted for
    attempts: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class TermsAcceptance(IdMixin, CreatedMixin, Base):
    __tablename__ = "terms_acceptances"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    document: Mapped[str] = mapped_column(String(20))  # terms | privacy
    version: Mapped[str] = mapped_column(String(20))


class IdentityLinkReview(IdMixin, TimestampMixin, Base):
    """Verified-email match that could not be auto-linked (duplicate/ambiguous). Resolved manually by Admin."""

    __tablename__ = "identity_link_reviews"
    email: Mapped[str] = mapped_column(String(320), index=True)
    source_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    candidate_user_ids: Mapped[list] = mapped_column(JSON)
    provider: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | linked | dismissed
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    resolution_note: Mapped[str | None] = mapped_column(String(500))


class TelegramLoginSession(IdMixin, CreatedMixin, Base):
    """Website login that is approved inside the Telegram bot (device-authorization flow, see docs/TELEGRAM-WEB-LOGIN.md).

    ``public_id`` travels in the deep link / QR code; ``secret_hash`` is the SHA-256 of the poll token that only the
    requesting browser holds, so whoever sees the link can never collect the session. Single use, short lived.
    """

    __tablename__ = "telegram_login_sessions"
    public_id: Mapped[str] = mapped_column(String(24), unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)  # pending|scanned|approved|denied|expired|consumed
    match_code: Mapped[str] = mapped_column(String(2))  # number shown on the website, must be picked in the bot
    decoys: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    req_ip: Mapped[str | None] = mapped_column(String(64))
    req_device: Mapped[str | None] = mapped_column(String(120))
    req_ua: Mapped[str | None] = mapped_column(String(300))
    scanned_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    deny_reason: Mapped[str | None] = mapped_column(String(40))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
