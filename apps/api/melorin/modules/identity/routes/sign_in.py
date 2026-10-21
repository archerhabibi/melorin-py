"""/auth: sign-in by e-mail code, password, Google, Telegram and web hand-off, plus refresh and logout."""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from melorin.core import audit, channel, flags, integrations
from melorin.core.crypto import decrypt
from melorin.core.config import get_settings
from melorin.core.deps import BotAuth, Session, main_store
from melorin.core.errors import AppError
from melorin.core.ratelimit import RateLimit, hit
from melorin.core.security import new_opaque_token, totp_counter, verify_password
from melorin.modules.identity import google as google_signin, service
from melorin.kernel.models.identity import User
from melorin.modules.identity.schemas import (
    EmailCodeRequest,
    EmailCodeVerify,
    GoogleLogin,
    PasswordLogin,
    RefreshRequest,
    TelegramBotLogin,
    TelegramLink,
    TelegramWebAppLogin,
    TokenPair,
    WebHandoffRedeem,
)
from melorin.kernel.models.stores import Store
from melorin.modules.identity.routes._common import (
    GOOGLE_NONCE_COOKIE,
    GOOGLE_NONCE_PATH,
    GOOGLE_NONCE_TTL,
    REFRESH_COOKIE,
    _after_signup,
    _refuse_admin_on_customer_channel,
    _set_refresh_cookie,
)


auth = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(RateLimit("auth", 30, 60))])


@auth.post("/email/request-code")
async def email_request_code(body: EmailCodeRequest, session: Session):
    dev_code = await service.request_email_code(session, body.email)
    return {"sent": True, **({"dev_code": dev_code} if dev_code else {})}


@auth.post("/email/verify-code", response_model=TokenPair)
async def email_verify_code(body: EmailCodeVerify, session: Session, request: Request, response: Response):
    site = await channel.site_channel(session, request)  # which store's website is this? (Host, verified by Core)
    user, created = await service.login_with_email_code(session, body.email, body.code)
    _refuse_admin_on_customer_channel(user)
    if created:
        await flags.ensure_enabled(session, "registration")
    await _after_signup(session, user, created, site.store_id, body.referral_code)
    await service.accept_terms(session, user, body.accept_terms_version)
    pair = await service.issue_tokens(session, user, site, ua=request.headers.get("user-agent"))
    await session.commit()
    _set_refresh_cookie(response, pair)
    return pair


@auth.post("/password/login", response_model=TokenPair)
async def password_login(body: PasswordLogin, session: Session, request: Request, response: Response):
    email = body.email.strip().lower()
    if not await hit(f"auth-account:{email}", 10, 900):
        raise AppError("ACCOUNT_LOGIN_THROTTLED", "تلاش‌های ورود برای این حساب موقتاً محدود شده است.", 429)
    user = await session.scalar(select(User).where(User.email == email).with_for_update())
    if not user or not await verify_password(body.password, user.password_hash) or not user.is_active:
        audit.security_event(session, "login_failed", user.id if user else None, {"email": email})
        await session.commit()
        raise AppError("INVALID_CREDENTIALS", "ایمیل یا رمز عبور نادرست است.", 401)
    if user.is_super_admin and not user.totp_enabled:
        audit.security_event(session, "admin_2fa_required", user.id)
        await session.commit()
        raise AppError("ADMIN_2FA_REQUIRED", "ابتدا احراز هویت دومرحله‌ای ادمین را فعال کنید.", 403)
    counter = None
    if user.totp_enabled:
        counter = totp_counter(decrypt(user.totp_secret_enc) or "", body.totp_code or "")
        if counter is None or (user.totp_last_counter is not None and counter <= user.totp_last_counter):
            audit.security_event(session, "totp_failed" if counter is None else "totp_replay", user.id)
            await session.commit()
            raise AppError("TOTP_REQUIRED", "کد تأیید دومرحله‌ای لازم، نادرست یا تکراری است.", 401)
        user.totp_last_counter = counter
    if user.is_super_admin:
        audit.record(session, "admin.login", actor_id=user.id, actor_type="admin")
        chan = channel.ADMIN_CHANNEL  # password + TOTP just succeeded: the one way to get an admin session
    else:
        chan = await channel.site_channel(session, request)
    pair = await service.issue_tokens(session, user, chan, ua=request.headers.get("user-agent"))
    await session.commit()
    _set_refresh_cookie(response, pair)
    return pair


@auth.get("/google/config")
async def google_config(session: Session, response: Response):
    """Public: lets the login pages learn at runtime whether Google Sign-In is on and which Client ID to use."""
    response.headers["Cache-Control"] = "no-store"
    return integrations.public_google(await integrations.get_google(session))


@auth.get("/google/nonce")
async def google_nonce(response: Response):
    """Public: a fresh single-use nonce for one Sign in with Google attempt. The value is returned (the page hands it to
    google.accounts.id.initialize so Google embeds it in the ID token) and also set as an httpOnly cookie; POST /auth/google
    accepts a token only when both match, so a leaked or replayed ID token is useless without this browser's cookie."""
    nonce = new_opaque_token(24)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        GOOGLE_NONCE_COOKIE,
        nonce,
        httponly=True,
        secure=not get_settings().is_dev,
        samesite="lax",
        max_age=GOOGLE_NONCE_TTL,
        path=GOOGLE_NONCE_PATH,
    )
    return {"nonce": nonce}


@auth.post("/google", response_model=TokenPair)
async def google_login(body: GoogleLogin, session: Session, request: Request, response: Response):
    cookies = getattr(request, "cookies", None) or {}
    user, created = await google_signin.login_with_google(session, body.id_token, cookies.get(GOOGLE_NONCE_COOKIE))
    cfg = await integrations.get_google(session)
    if user.is_super_admin and not cfg["admin_login"]:
        await session.rollback()
        raise AppError("GOOGLE_ADMIN_DISABLED", "ورود ادمین با Google غیرفعال است.", 403)
    if not user.is_super_admin and not cfg["store_login"]:
        await session.rollback()
        raise AppError("GOOGLE_STORE_DISABLED", "ورود مشتریان با Google غیرفعال است.", 403)
    if created:
        await flags.ensure_enabled(session, "registration")
    if user.is_super_admin:
        # Google must never bypass the admin second factor that /password/login enforces.
        if not user.totp_enabled:
            audit.security_event(session, "admin_2fa_required", user.id, {"via": "google"})
            await session.commit()
            raise AppError("ADMIN_2FA_REQUIRED", "ابتدا احراز هویت دومرحله‌ای ادمین را فعال کنید.", 403)
        counter = totp_counter(decrypt(user.totp_secret_enc) or "", body.totp_code or "")
        if counter is None or (user.totp_last_counter is not None and counter <= user.totp_last_counter):
            audit.security_event(session, "totp_failed" if counter is None else "totp_replay", user.id, {"via": "google"})
            await session.commit()
            raise AppError("TOTP_REQUIRED", "کد تأیید دومرحله‌ای لازم، نادرست یا تکراری است.", 401)
        user.totp_last_counter = counter
        audit.record(session, "admin.login", actor_id=user.id, actor_type="admin")
    chan = channel.ADMIN_CHANNEL if user.is_super_admin else await channel.site_channel(session, request)
    await _after_signup(session, user, created, chan.store_id, None)
    pair = await service.issue_tokens(session, user, chan, ua=request.headers.get("user-agent"))
    await session.commit()
    _set_refresh_cookie(response, pair)
    response.delete_cookie(GOOGLE_NONCE_COOKIE, path=GOOGLE_NONCE_PATH)  # single use: consumed by a successful sign-in
    return pair


@auth.post("/telegram/webapp", response_model=TokenPair)
async def telegram_webapp(body: TelegramWebAppLogin, session: Session, request: Request):
    """Telegram Mini App sign-in. The ``initData`` signature is made with ONE bot's token, so it proves the bot (= store)
    the user is in: the store is the one that owns that very token, never an id the client names."""
    store = await session.get(Store, body.store_id) if body.store_id else await main_store(session)
    if store is None or store.status != "active":
        raise AppError("TELEGRAM_DISABLED", "Telegram پیکربندی نشده است.", 400)
    token = get_settings().main_bot_token if store.kind == "main" else (decrypt(store.bot_token_enc) if store.bot_token_enc else "")
    if not token:  # no fall-back to the main bot's token for a reseller store (its signature would prove the wrong store)
        raise AppError("TELEGRAM_DISABLED", "Telegram پیکربندی نشده است.", 400)
    tg = service.verify_telegram_webapp(body.init_data, token)
    from melorin.modules.identity.schemas import TelegramProfile

    chan = channel.Channel(channel.BOT, store.id, store.bot_username, store.kind, store.status, store.owner_user_id)
    user, created = await service.login_with_telegram(
        session,
        TelegramProfile(telegram_id=tg["id"], first_name=tg.get("first_name"), last_name=tg.get("last_name"), username=tg.get("username")),
    )
    _refuse_admin_on_customer_channel(user)
    await _after_signup(session, user, created, chan.store_id, None)
    pair = await service.issue_tokens(session, user, chan, ua=request.headers.get("user-agent"))
    await session.commit()
    return pair


@auth.post("/telegram/bot", response_model=TokenPair)
async def telegram_bot_login(body: TelegramBotLogin, session: Session, bot: BotAuth):
    """Trusted bot runner exchanges a Telegram user (validated by Telegram itself) for a Core session of ITS store."""
    chan = await channel.bot_channel(session, bot, body.store_id)
    user, created = await service.login_with_telegram(session, body)
    _refuse_admin_on_customer_channel(user)
    await _after_signup(session, user, created, chan.store_id, body.referral_code)
    pair = await service.issue_tokens(session, user, chan, ua="telegram-bot")
    await session.commit()
    return pair


@auth.post("/telegram/link", response_model=TokenPair)
async def telegram_link(body: TelegramLink, session: Session, bot: BotAuth):
    chan = await channel.bot_channel(session, bot, body.store_id)
    user = await service.link_telegram(session, body.code, body)
    _refuse_admin_on_customer_channel(user)
    pair = await service.issue_tokens(session, user, chan, ua="telegram-bot")
    await session.commit()
    return pair


@auth.post("/web-handoff/redeem", response_model=TokenPair)
async def web_handoff_redeem(body: WebHandoffRedeem, session: Session, request: Request, response: Response):
    """The store website exchanges the single-use token from the bot's account button for a normal session."""
    site = await channel.site_channel(session, request)
    user = await service.redeem_web_handoff(session, body.token, site)
    pair = await service.issue_tokens(session, user, site, ua=request.headers.get("user-agent"))
    await session.commit()
    _set_refresh_cookie(response, pair)
    return pair


@auth.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, request: Request, response: Response, session: Session):
    raw = body.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise AppError("INVALID_REFRESH", "نشست نامعتبر است.", 401)
    pair = await service.rotate_refresh(session, raw, request)
    _set_refresh_cookie(response, pair)
    return pair


@auth.post("/logout")
async def logout(body: RefreshRequest, request: Request, response: Response, session: Session):
    raw = body.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if raw:
        await service.revoke_refresh(session, raw)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return {"ok": True}
