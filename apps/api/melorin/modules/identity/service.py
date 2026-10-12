import datetime as dt
import hashlib
import hmac
import json
import logging
import uuid
from urllib.parse import parse_qsl

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.core.email import email_available, send_email
from melorin.core.errors import AppError
from melorin.core.security import (
    create_access_token,
    new_numeric_code,
    new_opaque_token,
    refresh_expiry,
    token_hash,
)
from melorin.modules.identity.models import Identity, IdentityLinkReview, RefreshToken, TermsAcceptance, User, VerificationCode
from melorin.modules.identity.schemas import TelegramProfile, TokenPair

log = logging.getLogger(__name__)
CODE_TTL = dt.timedelta(minutes=10)
MAX_CODE_ATTEMPTS = 5


async def user_by_referral_code(session: AsyncSession, code: str | None) -> User | None:
    if not code:
        return None
    return await session.scalar(select(User).where(User.referral_code == code.strip()[:16]))


# ---------------- tokens ----------------
async def issue_tokens(session: AsyncSession, user: User, family: uuid.UUID | None = None, ua: str | None = None) -> TokenPair:
    if not user.is_active:
        raise AppError("UNAUTHORIZED", "حساب کاربری غیرفعال است.", 401)
    access, ttl = create_access_token(user.id, user.is_super_admin)
    raw = new_opaque_token()
    session.add(
        RefreshToken(user_id=user.id, token_hash=token_hash(raw), family_id=family or uuid.uuid4(), expires_at=refresh_expiry(), user_agent=ua)
    )
    return TokenPair(access_token=access, refresh_token=raw, expires_in=ttl, user_id=user.id, is_admin=user.is_super_admin)


async def rotate_refresh(session: AsyncSession, raw: str) -> TokenPair:
    rt = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash(raw)).with_for_update())
    if not rt:
        raise AppError("INVALID_REFRESH", "نشست نامعتبر است.", 401)
    if rt.revoked_at is not None:
        # Reuse of a rotated token => likely theft: revoke the whole family.
        await session.execute(update(RefreshToken).where(RefreshToken.family_id == rt.family_id).values(revoked_at=utcnow()))
        audit.security_event(session, "refresh_token_reuse", rt.user_id)
        await session.commit()
        raise AppError("INVALID_REFRESH", "نشست نامعتبر است.", 401)
    if rt.expires_at.replace(tzinfo=rt.expires_at.tzinfo or dt.UTC) < utcnow():
        raise AppError("INVALID_REFRESH", "نشست منقضی شده است.", 401)
    rt.revoked_at = utcnow()
    # Rotation is atomic: the old token is revoked before the replacement is
    # issued, and reuse of the old token revokes its whole family.
    user = await session.get(User, rt.user_id)
    if not user or not user.is_active:
        raise AppError("UNAUTHORIZED", "حساب غیرفعال است.", 401)
    pair = await issue_tokens(session, user, family=rt.family_id)
    await session.commit()
    return pair


async def revoke_refresh(session: AsyncSession, raw: str) -> None:
    await session.execute(update(RefreshToken).where(RefreshToken.token_hash == token_hash(raw)).values(revoked_at=utcnow()))
    await session.commit()


# ---------------- identities ----------------
async def find_identity(session: AsyncSession, provider: str, subject: str) -> Identity | None:
    return await session.scalar(select(Identity).where(Identity.provider == provider, Identity.subject == subject))


async def get_or_create_user_for_identity(
    session: AsyncSession, provider: str, subject: str, *, display_name: str | None, data: dict | None, verified: bool = True
) -> tuple[User, bool]:
    ident = await find_identity(session, provider, subject)
    if ident:
        if data:
            ident.data = data
        return await session.get(User, ident.user_id), False
    user = User(display_name=display_name, email=subject if provider == "email" else None)
    session.add(user)
    await session.flush()
    session.add(Identity(user_id=user.id, provider=provider, subject=subject, data=data, verified_at=utcnow() if verified else None))
    audit.record(session, "identity.created", actor_id=user.id, entity_type="user", entity_id=user.id, data={"provider": provider})
    return user, True


async def accept_terms(session: AsyncSession, user: User, version: str | None) -> None:
    if version:
        session.add(TermsAcceptance(user_id=user.id, document="terms", version=version))


# ---------------- email code (passwordless; also Guest Checkout) ----------------
def _norm_email(e: str) -> str:
    return e.strip().lower()


async def request_email_code(session: AsyncSession, email: str) -> str | None:
    email = _norm_email(email)
    if not await email_available():
        raise AppError("EMAIL_DISABLED", "ورود با کد ایمیلی در حال حاضر فعال نیست. از روش‌های دیگر ورود استفاده کنید.", 503)
    code = new_numeric_code()
    session.add(VerificationCode(purpose="email_login", target=email, code_hash=token_hash(email + code), expires_at=utcnow() + CODE_TTL))
    await session.commit()
    await send_email(email, "کد ورود Melorin", f"کد ورود شما: {code}\nاعتبار: ۱۰ دقیقه")
    return code if get_settings().is_dev else None


async def consume_code(session: AsyncSession, purpose: str, target: str, code: str) -> VerificationCode:
    vc = await session.scalar(
        select(VerificationCode)
        .where(VerificationCode.purpose == purpose, VerificationCode.target == target, VerificationCode.used_at.is_(None))
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if not vc or vc.expires_at.replace(tzinfo=vc.expires_at.tzinfo or dt.UTC) < utcnow() or vc.attempts >= MAX_CODE_ATTEMPTS:
        raise AppError("CODE_INVALID", "کد نامعتبر یا منقضی است.", 400)
    if not hmac.compare_digest(vc.code_hash, token_hash(target + code)):
        vc.attempts += 1
        audit.security_event(session, "code_failed", None, {"purpose": purpose})
        await session.commit()
        raise AppError("CODE_INVALID", "کد نامعتبر یا منقضی است.", 400)
    vc.used_at = utcnow()
    return vc


async def login_with_email_code(session: AsyncSession, email: str, code: str) -> tuple[User, bool]:
    email = _norm_email(email)
    await consume_code(session, "email_login", email, code)
    ident = await find_identity(session, "email", email)
    if ident:
        if not ident.verified_at:
            ident.verified_at = utcnow()
        return await session.get(User, ident.user_id), False
    # A user created without an email Identity (bootstrap admin, password-only accounts) already owns this
    # address: the verified code proves ownership, so link a verified Identity instead of duplicating the user.
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        session.add(Identity(user_id=existing.id, provider="email", subject=email, data=None, verified_at=utcnow()))
        audit.record(session, "identity.linked", actor_id=existing.id, entity_type="user", entity_id=existing.id, data={"provider": "email"})
        await session.flush()
        return existing, False
    user, created = await get_or_create_user_for_identity(session, "email", email, display_name=email.split("@")[0], data=None)
    return user, created


async def attach_email(session: AsyncSession, user: User, email: str, code: str) -> None:
    email = _norm_email(email)
    await consume_code(session, "email_login", email, code)  # proves ownership
    ident = await find_identity(session, "email", email)
    if ident and ident.user_id != user.id:
        # Verified match, but two non-identical users already exist. Never merge automatically.
        session.add(IdentityLinkReview(email=email, source_user_id=user.id, candidate_user_ids=[str(ident.user_id)], provider="email", reason="verified_email_matches_other_user"))
        audit.security_event(session, "identity_link_conflict", user.id, {"email": email, "candidate_user_id": str(ident.user_id)})
        await session.commit()
        raise AppError("IDENTITY_LINK_REVIEW", "این ایمیل به حساب دیگری متصل است و برای بررسی دستی گزارش شد.", 409)
    if not ident:
        session.add(Identity(user_id=user.id, provider="email", subject=email, verified_at=utcnow()))
    if not user.email:
        user.email = email
    audit.record(session, "identity.linked", actor_id=user.id, entity_type="user", entity_id=user.id, data={"provider": "email"})
    await session.commit()


# ---------------- Google ----------------
async def verify_google_token(id_token: str) -> dict:
    s = get_settings()
    if not s.google_client_id:
        raise AppError("GOOGLE_DISABLED", "ورود با Google پیکربندی نشده است.", 400)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token})
    if r.status_code != 200:
        raise AppError("GOOGLE_INVALID", "توکن Google نامعتبر است.", 401)
    data = r.json()
    if data.get("aud") != s.google_client_id or data.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise AppError("GOOGLE_INVALID", "توکن Google نامعتبر است.", 401)
    return data


async def login_with_google(session: AsyncSession, id_token: str) -> User:
    g = await verify_google_token(id_token)
    sub, email = g["sub"], (g.get("email") or "").lower() or None
    ident = await find_identity(session, "google", sub)
    if ident:
        return await session.get(User, ident.user_id)
    user: User | None = None
    email_verified = email and str(g.get("email_verified")).lower() == "true"
    # Verified email may connect to the existing central User. An ambiguous/conflicting
    # match is recorded for Admin review, never guessed or merged.
    if email_verified:
        e_idents = (await session.scalars(select(Identity).where(Identity.provider == "email", Identity.subject == email, Identity.verified_at.is_not(None)))).all()
        candidate_ids = {i.user_id for i in e_idents}
        if len(candidate_ids) == 1:
            user = await session.get(User, next(iter(candidate_ids)))
        elif len(candidate_ids) > 1:
            user = User(display_name=g.get("name"), is_guest=True)
            session.add(user); await session.flush()
            session.add(IdentityLinkReview(email=email, source_user_id=user.id, candidate_user_ids=[str(x) for x in candidate_ids], provider="google", reason="multiple_verified_email_users"))
            audit.security_event(session, "identity_link_conflict", user.id, {"email": email, "candidate_user_ids": [str(x) for x in candidate_ids]})
        elif await _email_taken(session, email):
            # User.email can be populated without an Identity in legacy data.
            owner_id = await session.scalar(select(User.id).where(User.email == email))
            user = User(display_name=g.get("name"), is_guest=True)
            session.add(user); await session.flush()
            session.add(IdentityLinkReview(email=email, source_user_id=user.id, candidate_user_ids=[str(owner_id)], provider="google", reason="email_field_conflict"))
            audit.security_event(session, "identity_link_conflict", user.id, {"email": email, "candidate_user_id": str(owner_id)})
    if user is None:
        user = User(display_name=g.get("name"), email=email if email_verified else None)
        session.add(user)
        await session.flush()
    session.add(Identity(user_id=user.id, provider="google", subject=sub, verified_at=utcnow(), data={"email": email, "email_verified": bool(email_verified)}))
    audit.record(session, "identity.linked", actor_id=user.id, entity_type="user", entity_id=user.id, data={"provider": "google"})
    return user


async def _email_taken(session: AsyncSession, email: str) -> bool:
    return (await session.scalar(select(User.id).where(User.email == email))) is not None


# ---------------- Telegram ----------------
def verify_telegram_webapp(init_data: str, bot_token: str, max_age: int = 86400) -> dict:
    """https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app"""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(calc, received):
        raise AppError("TELEGRAM_INVALID", "داده Telegram نامعتبر است.", 401)
    if int(pairs.get("auth_date", "0")) < int(utcnow().timestamp()) - max_age:
        raise AppError("TELEGRAM_EXPIRED", "داده Telegram منقضی شده است.", 401)
    return json.loads(pairs.get("user", "{}"))


async def login_with_telegram(session: AsyncSession, p: TelegramProfile) -> tuple[User, bool]:
    name = " ".join(x for x in [p.first_name, p.last_name] if x) or p.username
    return await get_or_create_user_for_identity(
        session, "telegram", str(p.telegram_id), display_name=name, data={"username": p.username, "lang": p.language_code}
    )


async def create_link_code(session: AsyncSession, user: User) -> str:
    code = new_opaque_token(9)
    session.add(VerificationCode(purpose="telegram_link", target="link", code_hash=token_hash("link" + code), user_id=user.id, expires_at=utcnow() + CODE_TTL))
    await session.commit()
    return code


async def link_telegram(session: AsyncSession, code: str, p: TelegramProfile) -> User:
    vc = await session.scalar(
        select(VerificationCode)
        .where(VerificationCode.purpose == "telegram_link", VerificationCode.code_hash == token_hash("link" + code), VerificationCode.used_at.is_(None))
        .with_for_update()
    )
    if not vc or vc.expires_at.replace(tzinfo=vc.expires_at.tzinfo or dt.UTC) < utcnow():
        raise AppError("CODE_INVALID", "کد اتصال نامعتبر یا منقضی است.", 400)
    user = await session.get(User, vc.user_id)
    ident = await find_identity(session, "telegram", str(p.telegram_id))
    if ident and ident.user_id != user.id:
        audit.security_event(session, "link_conflict", user.id, {"telegram_id": p.telegram_id})
        await session.commit()
        raise AppError("IDENTITY_IN_USE", "این حساب Telegram به کاربر دیگری متصل است. برای ادغام با پشتیبانی تماس بگیرید.", 409)
    if not ident:
        session.add(Identity(user_id=user.id, provider="telegram", subject=str(p.telegram_id), verified_at=utcnow(), data={"username": p.username}))
    vc.used_at = utcnow()
    user.is_guest = False
    audit.record(session, "identity.linked", actor_id=user.id, entity_type="user", entity_id=user.id, data={"provider": "telegram"})
    await session.commit()
    return user
