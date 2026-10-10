import datetime as dt
import secrets
import uuid

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint, Uuid
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


class VerificationCode(IdMixin, CreatedMixin, Base):
    """One-time codes: email login/verify and Telegram account linking."""

    __tablename__ = "verification_codes"
    purpose: Mapped[str] = mapped_column(String(30), index=True)  # email_login | telegram_link
    target: Mapped[str] = mapped_column(String(320), index=True)  # email address or user id
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
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
