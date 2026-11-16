"""Re-authentication for sensitive linking changes (docs/25, spec 7.4).

Password accounts prove themselves with the current password. Passwordless accounts prove control of their verified
primary e-mail with a one-time code (purpose ``identity_reauth``, bound to the user id, single use).
An account with neither a password nor a verified e-mail (Telegram/Google only) keeps the session as its only proof;
``unlink`` still refuses to remove the last usable sign-in method.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit as platform_audit
from melorin.core.email import email_available, send_email
from melorin.core.errors import AppError
from melorin.core.security import new_numeric_code, token_hash, verify_password
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.kernel.models.identity import User, VerificationCode
from melorin.modules.identity import service

PURPOSE = "identity_reauth"


def method_for(user: User) -> str:
    """Which proof this account must give: ``password`` | ``email_code`` | ``session``."""
    if user.password_hash:
        return "password"
    return "email_code" if user.email else "session"


async def start_email_code(session: AsyncSession, user: User) -> str | None:
    """Mail a one-time code to the verified primary e-mail. Returns the code only in dev."""
    if method_for(user) != "email_code" or not user.email:
        raise AppError("REAUTH_NOT_APPLICABLE", "برای این حساب کد ایمیلی لازم نیست.", 400)
    if not await email_available():
        raise AppError("EMAIL_DISABLED", "ارسال ایمیل در حال حاضر فعال نیست.", 503)
    target, code = str(user.id), new_numeric_code()
    session.add(
        VerificationCode(purpose=PURPOSE, target=target, code_hash=token_hash(target + code), expires_at=utcnow() + service.CODE_TTL)
    )
    await session.commit()
    await send_email(user.email, "کد تأیید تغییر روش ورود Melorin", f"کد شما: {code}\nاعتبار: ۱۰ دقیقه")
    return code if get_settings().is_dev else None


async def require(session: AsyncSession, user: User, *, password: str | None, code: str | None) -> None:
    """Raise ``REAUTH_REQUIRED`` unless the caller gave the proof that fits the account."""
    method = method_for(user)
    if method == "password":
        assert user.password_hash is not None
        if not password or not await verify_password(password, user.password_hash):
            platform_audit.security_event(session, "identity_unlink_reauth_failed", user.id)
            await session.commit()
            raise AppError("REAUTH_REQUIRED", "برای این تغییر رمز فعلی لازم است.", 401)
    elif method == "email_code":
        if not code:
            raise AppError("REAUTH_REQUIRED", "برای این تغییر کد ایمیلی لازم است.", 401, {"method": method})
        try:
            await service.consume_code(session, PURPOSE, str(user.id), code)
        except AppError as e:
            platform_audit.security_event(session, "identity_unlink_reauth_failed", user.id)
            await session.commit()
            raise AppError("REAUTH_REQUIRED", "کد نامعتبر یا منقضی است.", 401, {"method": method}) from e
