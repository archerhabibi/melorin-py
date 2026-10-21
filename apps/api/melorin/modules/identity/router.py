from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from melorin.core import audit, channel, flags, integrations
from melorin.core.crypto import decrypt, encrypt
from melorin.core.config import get_settings
from melorin.core.deps import AdminUser, BotAuth, CurrentAuth, CurrentUser, Session, main_store
from melorin.core.errors import AppError
from melorin.core.ratelimit import RateLimit, hit
from melorin.core.security import new_opaque_token, totp_counter, totp_new_secret, verify_password, hash_password
from melorin.modules.identity import service
from melorin.kernel.models.identity import User
from melorin.modules.identity.schemas import (
    AdminPasswordChange,
    EmailCodeRequest,
    EmailCodeVerify,
    GoogleLink,
    GoogleLogin,
    IdentityOut,
    LinkCodeOut,
    MeOut,
    MeUpdate,
    PasswordLogin,
    RefreshRequest,
    SetPassword,
    TelegramBotLogin,
    TelegramLink,
    TelegramWebAppLogin,
    TokenPair,
    TotpEnable,
    TotpSetupOut,
    WebHandoffIn,
    WebHandoffOut,
    WebHandoffRedeem,
)
from melorin.modules.referral import service as referral
from melorin.kernel.models.stores import Store, StoreMembership

auth = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(RateLimit("auth", 30, 60))])
me = APIRouter(prefix="/me", tags=["me"])
REFRESH_COOKIE = "melorin_refresh"
GOOGLE_NONCE_COOKIE = "melorin_gnonce"
GOOGLE_NONCE_PATH = "/api/v1/auth/google"
GOOGLE_NONCE_TTL = 600


def _set_refresh_cookie(response: Response, pair: TokenPair) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        pair.refresh_token,
        httponly=True,
        secure=not get_settings().is_dev,
        samesite="lax",
        max_age=get_settings().refresh_ttl_days * 86400,
        path="/api/v1/auth",
    )


async def _after_signup(session, user: User, created: bool, store_id, ref_code: str | None):
    """Attach the sign-up (and its referral) to the store of the CHANNEL the user came through, never to a client-sent id."""
    if created:
        store = await session.get(Store, store_id) if store_id else await main_store(session)
        referrer = await service.user_by_referral_code(session, ref_code)
        if store:
            await referral.attach(session, store.id, user, referrer)


def _refuse_admin_on_customer_channel(user: User) -> None:
    """Admins sign in only at the admin panel (password + TOTP): email codes, store sites and bots never mint admin sessions."""
    if user.is_super_admin:
        raise AppError("ADMIN_USE_PANEL", "ورود مدیران فقط از پنل مدیریت انجام می‌شود.", 403)


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
    user, created = await service.login_with_google(session, body.id_token, cookies.get(GOOGLE_NONCE_COOKIE))
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


# ---------------- /me ----------------
def _me_out(u: User) -> MeOut:
    return MeOut(
        id=u.id,
        display_name=u.display_name,
        email=u.email,
        is_admin=u.is_super_admin,
        is_guest=u.is_guest,
        totp_enabled=u.totp_enabled,
        referral_code=u.referral_code,
        identities=[
            IdentityOut(
                id=i.id,
                provider=i.provider,
                subject=i.subject if i.provider != "telegram" else i.subject,
                verified=i.verified_at is not None,
            )
            for i in u.identities
        ],
    )


@me.get("", response_model=MeOut)
async def get_me(user: CurrentUser, session: Session):
    await session.refresh(user, ["identities"])
    return _me_out(user)


@me.patch("", response_model=MeOut)
async def update_me(body: MeUpdate, user: CurrentUser, session: Session):
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(user, k, v)
    await session.commit()
    await session.refresh(user, ["identities"])
    return _me_out(user)


@me.get("/stores")
async def my_stores(auth: CurrentAuth, session: Session):
    """The stores this SESSION may see. A store's own site/bot sees only that store; the main store (account hub) also lists
    the stores the user owns (the reseller panel needs them); the admin panel sees every membership."""
    user, claims = auth.user, auth.claims
    q = select(Store, StoreMembership).join(StoreMembership, StoreMembership.store_id == Store.id).where(StoreMembership.user_id == user.id)
    if not claims.is_admin:
        main = await main_store(session)
        if claims.store_id == main.id:
            q = q.where((Store.id == main.id) | (Store.owner_user_id == user.id))
        else:
            q = q.where(Store.id == claims.store_id)
    rows = (await session.execute(q)).all()
    return [{"id": s.id, "name": s.name, "kind": s.kind, "slug": s.slug, "role": m.role} for s, m in rows]


@me.post("/link-codes/telegram", response_model=LinkCodeOut)
async def create_telegram_link_code(user: CurrentUser, session: Session):
    code = await service.create_link_code(session, user)
    store = await main_store(session)
    link = f"https://t.me/{store.bot_username}?start=link_{code}" if store.bot_username else None
    return LinkCodeOut(code=code, expires_in=600, telegram_deeplink=link)


@me.post("/web-handoff", response_model=WebHandoffOut)
async def create_web_handoff(body: WebHandoffIn, auth: CurrentAuth, session: Session):
    """Called by the Telegram bots (with the user's own bot session): returns the store-website URL that opens this user's
    account already signed in. The URL is built here, from the store's domain (or the main store web URL)."""
    user, claims = auth.user, auth.claims
    if user.is_super_admin or claims.is_admin or claims.channel != channel.BOT:
        raise AppError("ADMIN_USE_PANEL", "ورود مدیران فقط از پنل مدیریت انجام می‌شود.", 403)
    if not await hit(f"web-handoff:{user.id}", 10, 60):
        raise AppError("RATE_LIMITED", "درخواست‌ها زیاد است؛ کمی بعد دوباره امتحان کنید.", 429)
    if body.store_id is not None and body.store_id != claims.store_id:
        raise channel.mismatch()  # a bot session can only hand off to its own store's website
    store = await session.get(Store, claims.store_id)
    domain = ((store.domain if store else None) or "").strip().lower().rstrip(".")
    base = f"https://{domain}" if domain else get_settings().store_web_url.rstrip("/")
    token = await service.create_web_handoff(session, user, claims.store_id)
    await session.refresh(user, ["identities"])
    return WebHandoffOut(url=f"{base}/#/auth/handoff?t={token}", google_linked=any(i.provider == "google" for i in user.identities))


@me.post("/identities/google")
async def attach_google(body: GoogleLink, user: CurrentUser, session: Session, request: Request, response: Response):
    """Link a Google account to the signed-in user (same nonce-cookie binding as Google sign-in)."""
    cookies = getattr(request, "cookies", None) or {}
    await service.link_google(session, user, body.id_token, cookies.get(GOOGLE_NONCE_COOKIE))
    response.delete_cookie(GOOGLE_NONCE_COOKIE, path=GOOGLE_NONCE_PATH)
    return {"ok": True}


@me.post("/identities/email")
async def attach_email(body: EmailCodeVerify, user: CurrentUser, session: Session):
    await service.attach_email(session, user, body.email, body.code)
    return {"ok": True}


@auth.post("/admin/password")
async def change_admin_password(body: AdminPasswordChange, admin: AdminUser, session: Session):
    if not await verify_password(body.current_password, admin.password_hash):
        audit.security_event(session, "admin.password_change_failed", admin.id)
        await session.commit()
        raise AppError("INVALID_CURRENT_PASSWORD", "رمز فعلی نادرست است.", 401)
    if body.current_password == body.new_password:
        raise AppError("PASSWORD_UNCHANGED", "رمز جدید باید با رمز فعلی متفاوت باشد.", 400)
    admin.password_hash = await hash_password(body.new_password)
    audit.record(session, "admin.password_changed", actor_id=admin.id, actor_type="admin", entity_type="user", entity_id=admin.id)
    await session.commit()
    return {"ok": True}


@me.post("/password")
async def set_password(body: SetPassword, user: CurrentUser, session: Session):
    if not user.email:
        raise AppError("EMAIL_REQUIRED", "ابتدا یک ایمیل تأییدشده اضافه کنید.", 400)
    user.password_hash = await hash_password(body.password)
    audit.record(session, "user.password_set", actor_id=user.id, entity_type="user", entity_id=user.id)
    await session.commit()
    return {"ok": True}


@me.post("/2fa/setup", response_model=TotpSetupOut)
async def totp_setup(user: CurrentUser, session: Session):
    secret = totp_new_secret()
    user.totp_secret_enc = encrypt(secret)
    user.totp_enabled = False
    await session.commit()
    return TotpSetupOut(secret=secret, otpauth_url=f"otpauth://totp/Melorin:{user.email or user.id}?secret={secret}&issuer=Melorin")


@me.post("/2fa/enable")
async def totp_enable(body: TotpEnable, user: CurrentUser, session: Session):
    counter = totp_counter(decrypt(user.totp_secret_enc) or "", body.code) if user.totp_secret_enc else None
    if counter is None:
        raise AppError("TOTP_INVALID", "کد نادرست است.", 400)
    user.totp_enabled = True
    user.totp_last_counter = counter
    audit.record(session, "user.2fa_enabled", actor_id=user.id, entity_type="user", entity_id=user.id)
    await session.commit()
    return {"ok": True}
