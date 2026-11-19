"""Re-authentication for sensitive linking changes (docs/25, spec 7.4).

Every account proves control of a factor it really owns, strongest first:

* ``password``      - the current password;
* ``email_code``    - a one-time code mailed to the verified primary e-mail;
* ``google``        - a fresh Google ID token (bound to this browser's nonce cookie) of one of the person's Google logins;
* ``telegram_code`` - a one-time code delivered by the bot to the person's linked Telegram chat;
* ``session``       - only for an account that has none of the above (nothing to prove with).

Codes use purpose ``identity_reauth``, are bound to the user id and are single use. ``unlink`` additionally refuses to
remove the last usable sign-in method.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit as platform_audit, events
from melorin.core.email import email_available, send_email
from melorin.core.errors import AppError
from melorin.core.security import new_numeric_code, token_hash, verify_password, safe_equal
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.kernel.models.identity import Identity, User, VerificationCode
from melorin.modules.identity import google as google_signin, service

PURPOSE = "identity_reauth"


async def _active_identities(session: AsyncSession, user: User, provider: str) -> list[Identity]:
    """Active logins of ``provider`` owned by this account or by another account of the same person."""
    owner = Identity.user_id == user.id
    if user.person_id is not None:
        owner = owner | (Identity.person_id == user.person_id)
    rows = await session.scalars(select(Identity).where(owner, Identity.provider == provider, Identity.status == "active"))
    return list(rows.all())


async def method_for(session: AsyncSession, user: User) -> str:
    """Which proof this account must give: ``password`` | ``email_code`` | ``google`` | ``telegram_code`` | ``session``."""
    if user.password_hash:
        return "password"
    if user.email:
        return "email_code"
    if await _active_identities(session, user, "google"):
        return "google"
    if await _active_identities(session, user, "telegram"):
        return "telegram_code"
    return "session"


async def _store_code(session: AsyncSession, user: User) -> str:
    target, code = str(user.id), new_numeric_code()
    session.add(
        VerificationCode(purpose=PURPOSE, target=target, code_hash=token_hash(target + code), expires_at=utcnow() + service.CODE_TTL)
    )
    return code


async def start_email_code(session: AsyncSession, user: User) -> str | None:
    """Mail a one-time code to the verified primary e-mail. Returns the code only in dev."""
    if await method_for(session, user) != "email_code" or not user.email:
        raise AppError("REAUTH_NOT_APPLICABLE", "برای این حساب کد ایمیلی لازم نیست.", 400)
    if not await email_available():
        raise AppError("EMAIL_DISABLED", "ارسال ایمیل در حال حاضر فعال نیست.", 503)
    code = await _store_code(session, user)
    await session.commit()
    await send_email(user.email, "کد تأیید تغییر روش ورود Melorin", f"کد شما: {code}\nاعتبار: ۱۰ دقیقه")
    return code if get_settings().is_dev else None


async def start_telegram_code(session: AsyncSession, user: User) -> str | None:
    """Send a one-time code to the person's linked Telegram chat through the bot. Returns the code only in dev."""
    if await method_for(session, user) != "telegram_code":
        raise AppError("REAUTH_NOT_APPLICABLE", "برای این حساب کد تلگرام لازم نیست.", 400)
    # the Telegram login may sit on another account of the same person: the bot writes to whoever really owns it
    chat_owner = (await _active_identities(session, user, "telegram"))[0].user_id
    code = await _store_code(session, user)
    await events.emit_user_notice(
        session,
        chat_owner,
        None,
        "identity_reauth",
        "🔐 کد تأیید تغییر روش ورود",
        f"کد شما: {code}\nاعتبار: ۱۰ دقیقه\nاگر خودتان درخواست نداده‌اید این پیام را نادیده بگیرید.",
        payload_dedup_key=f"identity_reauth:{user.id}:{code}",
    )
    platform_audit.security_event(session, "identity_reauth_telegram_started", user.id)
    await session.commit()
    return code if get_settings().is_dev else None


async def _verify_google(session: AsyncSession, user: User, id_token: str | None, nonce: str | None) -> None:
    """A fresh, nonce-bound Google ID token must belong to one of the person's own Google logins."""
    if not id_token:
        raise AppError("REAUTH_REQUIRED", "برای این تغییر باید دوباره با Google تأیید کنید.", 401, {"method": "google"})
    try:
        claims = await google_signin.google_claims(session, id_token, nonce)
    except AppError as e:
        platform_audit.security_event(session, "identity_unlink_reauth_failed", user.id)
        await session.commit()
        raise AppError("REAUTH_REQUIRED", "تأیید Google نامعتبر یا منقضی است.", 401, {"method": "google"}) from e
    owned = {i.subject for i in await _active_identities(session, user, "google")}
    if not any(safe_equal(str(claims["sub"]), sub) for sub in owned):
        platform_audit.security_event(session, "identity_unlink_reauth_failed", user.id, {"reason": "foreign_google_account"})
        await session.commit()
        raise AppError("REAUTH_REQUIRED", "این حساب Google متعلق به پروفایل شما نیست.", 401, {"method": "google"})


async def require(
    session: AsyncSession,
    user: User,
    *,
    password: str | None,
    code: str | None,
    google_id_token: str | None = None,
    google_nonce: str | None = None,
) -> None:
    """Raise ``REAUTH_REQUIRED`` unless the caller gave the proof that fits the account."""
    method = await method_for(session, user)
    if method == "password":
        assert user.password_hash is not None
        if not password or not await verify_password(password, user.password_hash):
            platform_audit.security_event(session, "identity_unlink_reauth_failed", user.id)
            await session.commit()
            raise AppError("REAUTH_REQUIRED", "برای این تغییر رمز فعلی لازم است.", 401)
    elif method == "google":
        await _verify_google(session, user, google_id_token, google_nonce)
    elif method in ("email_code", "telegram_code"):
        if not code:
            what = "ایمیلی" if method == "email_code" else "تلگرام"
            raise AppError("REAUTH_REQUIRED", f"برای این تغییر کد {what} لازم است.", 401, {"method": method})
        try:
            await service.consume_code(session, PURPOSE, str(user.id), code)
        except AppError as e:
            platform_audit.security_event(session, "identity_unlink_reauth_failed", user.id)
            await session.commit()
            raise AppError("REAUTH_REQUIRED", "کد نامعتبر یا منقضی است.", 401, {"method": method}) from e
