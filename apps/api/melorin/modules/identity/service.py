import datetime as dt
import hashlib
import hmac
import json
import logging
import uuid
from urllib.parse import parse_qsl

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.channel import Channel
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
from melorin.kernel.models.identity import Identity, IdentityLinkReview, RefreshToken, TermsAcceptance, User, VerificationCode
from melorin.modules.identity.lookup import find_identity
from melorin.modules.identity.schemas import TelegramProfile, TokenPair

log = logging.getLogger(__name__)
CODE_TTL = dt.timedelta(minutes=10)
MAX_CODE_ATTEMPTS = 5


async def user_by_referral_code(session: AsyncSession, code: str | None) -> User | None:
    if not code:
        return None
    return await session.scalar(select(User).where(User.referral_code == code.strip()[:16]))


# ---------------- tokens ----------------
async def issue_tokens(
    session: AsyncSession, user: User, chan: Channel, family: uuid.UUID | None = None, ua: str | None = None
) -> TokenPair:
    """Open (or rotate) a session. ``chan`` is the channel Core itself verified (``core.channel``): it is written into the
    access token and into the refresh-token family, so the session can never be used for, or moved to, another store."""
    if not user.is_active:
        raise AppError("UNAUTHORIZED", "حساب کاربری غیرفعال است.", 401)
    if chan.is_admin != bool(user.is_super_admin):
        # An admin account never gets a customer session through a store channel, and nobody else gets an admin one.
        raise AppError("ADMIN_USE_PANEL", "ورود مدیران فقط از پنل مدیریت انجام می‌شود.", 403)
    chan.ensure_open_for(user)
    access, ttl = create_access_token(user.id, chan.is_admin, store_id=chan.store_id, channel=chan.kind)
    raw = new_opaque_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash(raw),
            family_id=family or uuid.uuid4(),
            expires_at=refresh_expiry(),
            user_agent=ua,
            channel=chan.kind,
            store_id=chan.store_id,
        )
    )
    return TokenPair(
        access_token=access,
        refresh_token=raw,
        expires_in=ttl,
        user_id=user.id,
        is_admin=chan.is_admin,
        channel=chan.kind,
        store_id=chan.store_id,
    )


async def rotate_refresh(session: AsyncSession, raw: str, request=None) -> TokenPair:
    from melorin.core import channel as ch
    from melorin.kernel.models.stores import Store

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
    if rt.channel not in ch.CHANNELS or (rt.channel == ch.ADMIN) != (rt.store_id is None):
        raise AppError("INVALID_REFRESH", "نشست قدیمی است؛ دوباره وارد شوید.", 401)  # legacy / unbound family
    user = await session.get(User, rt.user_id)
    if not user or not user.is_active:
        raise AppError("UNAUTHORIZED", "حساب غیرفعال است.", 401)
    if rt.channel == ch.ADMIN:
        chan = ch.ADMIN_CHANNEL
    else:
        store = await session.get(Store, rt.store_id)
        if store is None:
            raise AppError("INVALID_REFRESH", "نشست نامعتبر است.", 401)
        if rt.channel == ch.SITE and request is not None:
            # A browser refresh must still come through the store's own domain (cookies are per host, this is defence in depth).
            live = await ch.site_channel(session, request, hint=rt.store_id)
            if live.store_id != rt.store_id:
                raise ch.mismatch()
        chan = ch.Channel(rt.channel, store.id, None, store.kind, store.status, store.owner_user_id)
    rt.revoked_at = utcnow()
    # Rotation is atomic: the old token is revoked before the replacement is issued (same channel, same store), and
    # reuse of the old token revokes its whole family.
    pair = await issue_tokens(session, user, chan, family=rt.family_id)
    await session.commit()
    return pair


async def revoke_refresh(session: AsyncSession, raw: str) -> None:
    await session.execute(update(RefreshToken).where(RefreshToken.token_hash == token_hash(raw)).values(revoked_at=utcnow()))
    await session.commit()


# ---------------- identities ----------------
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
        audit.record(
            session, "identity.linked", actor_id=existing.id, entity_type="user", entity_id=existing.id, data={"provider": "email"}
        )
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
        session.add(
            IdentityLinkReview(
                email=email,
                source_user_id=user.id,
                candidate_user_ids=[str(ident.user_id)],
                provider="email",
                reason="verified_email_matches_other_user",
            )
        )
        audit.security_event(session, "identity_link_conflict", user.id, {"email": email, "candidate_user_id": str(ident.user_id)})
        await session.commit()
        raise AppError("IDENTITY_LINK_REVIEW", "این ایمیل به حساب دیگری متصل است و برای بررسی دستی گزارش شد.", 409)
    if not ident:
        session.add(Identity(user_id=user.id, provider="email", subject=email, verified_at=utcnow()))
    if not user.email:
        user.email = email
    audit.record(session, "identity.linked", actor_id=user.id, entity_type="user", entity_id=user.id, data={"provider": "email"})
    await session.commit()


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
    session.add(
        VerificationCode(
            purpose="telegram_link", target="link", code_hash=token_hash("link" + code), user_id=user.id, expires_at=utcnow() + CODE_TTL
        )
    )
    await session.commit()
    return code


HANDOFF_TTL = dt.timedelta(minutes=2)


async def create_web_handoff(session: AsyncSession, user: User, store_id: uuid.UUID) -> str:
    """Single-use, 2-minute token that signs the (already authenticated) Telegram user into the SAME store's website."""
    token = new_opaque_token(32)
    session.add(
        VerificationCode(
            purpose="web_handoff",
            target=str(user.id),
            code_hash=token_hash("handoff" + token),
            user_id=user.id,
            store_id=store_id,
            expires_at=utcnow() + HANDOFF_TTL,
        )
    )
    audit.record(session, "auth.web_handoff_created", actor_id=user.id, entity_type="user", entity_id=user.id)
    await session.commit()
    return token


async def redeem_web_handoff(session: AsyncSession, token: str, site: Channel) -> User:
    """``site`` is the channel of the website that is redeeming (from its Host): the token only works where it was minted."""
    vc = await session.scalar(
        select(VerificationCode)
        .where(
            VerificationCode.purpose == "web_handoff",
            VerificationCode.code_hash == token_hash("handoff" + (token or "")),
            VerificationCode.used_at.is_(None),
        )
        .with_for_update()
    )
    if not vc or vc.expires_at.replace(tzinfo=vc.expires_at.tzinfo or dt.UTC) < utcnow():
        raise AppError("HANDOFF_INVALID", "لینک ورود نامعتبر یا منقضی است؛ دوباره از ربات تلگرام بزنید.", 400)
    vc.used_at = utcnow()  # single use, even if the account turns out to be refused below
    if vc.store_id is None or vc.store_id != site.store_id:
        audit.security_event(session, "handoff_store_mismatch", vc.user_id, {"minted_for": str(vc.store_id), "used_on": str(site.store_id)})
        await session.commit()
        raise AppError("HANDOFF_INVALID", "لینک ورود نامعتبر یا منقضی است؛ دوباره از ربات تلگرام بزنید.", 400)
    user = await session.get(User, vc.user_id)
    if user is None or not user.is_active:
        raise AppError("UNAUTHORIZED", "حساب کاربری غیرفعال است.", 401)
    if user.is_super_admin:
        raise AppError("ADMIN_USE_PANEL", "ورود مدیران فقط از پنل مدیریت انجام می‌شود.", 403)
    audit.record(session, "auth.web_handoff_redeemed", actor_id=user.id, entity_type="user", entity_id=user.id)
    return user


async def link_telegram(session: AsyncSession, code: str, p: TelegramProfile) -> User:
    vc = await session.scalar(
        select(VerificationCode)
        .where(
            VerificationCode.purpose == "telegram_link",
            VerificationCode.code_hash == token_hash("link" + code),
            VerificationCode.used_at.is_(None),
        )
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
        session.add(
            Identity(user_id=user.id, provider="telegram", subject=str(p.telegram_id), verified_at=utcnow(), data={"username": p.username})
        )
    vc.used_at = utcnow()
    user.is_guest = False
    audit.record(session, "identity.linked", actor_id=user.id, entity_type="user", entity_id=user.id, data={"provider": "telegram"})
    await session.commit()
    return user
