from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from melorin.core import audit, flags
from melorin.core.crypto import decrypt, encrypt
from melorin.core.config import get_settings
from melorin.core.deps import CurrentUser, Session, main_store, require_bot_service
from melorin.core.errors import AppError
from melorin.core.ratelimit import RateLimit, hit
from melorin.core.security import totp_counter, totp_new_secret, totp_verify, verify_password, hash_password
from melorin.modules.identity import service
from melorin.modules.identity.models import Identity, User
from melorin.modules.identity.schemas import (
    AdminPasswordChange, EmailCodeRequest, EmailCodeVerify, GoogleLogin, IdentityOut, LinkCodeOut, MeOut, MeUpdate, PasswordLogin,
    RefreshRequest, SetPassword, TelegramBotLogin, TelegramLink, TelegramWebAppLogin, TokenPair, TotpEnable, TotpSetupOut,
)
from melorin.modules.referral import service as referral
from melorin.modules.stores.models import Store, StoreMembership

auth = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(RateLimit("auth", 30, 60))])
me = APIRouter(prefix="/me", tags=["me"])
REFRESH_COOKIE = "melorin_refresh"


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
    if created:
        store = await session.get(Store, store_id) if store_id else await main_store(session)
        referrer = await service.user_by_referral_code(session, ref_code)
        if store:
            await referral.attach(session, store.id, user, referrer)


@auth.post("/email/request-code")
async def email_request_code(body: EmailCodeRequest, session: Session):
    dev_code = await service.request_email_code(session, body.email)
    return {"sent": True, **({"dev_code": dev_code} if dev_code else {})}


@auth.post("/email/verify-code", response_model=TokenPair)
async def email_verify_code(body: EmailCodeVerify, session: Session, request: Request, response: Response):
    user, created = await service.login_with_email_code(session, body.email, body.code)
    if created:
        await flags.ensure_enabled(session, "registration")
    await _after_signup(session, user, created, None, body.referral_code)
    await service.accept_terms(session, user, body.accept_terms_version)
    pair = await service.issue_tokens(session, user, ua=request.headers.get("user-agent"))
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
    pair = await service.issue_tokens(session, user, ua=request.headers.get("user-agent"))
    await session.commit()
    _set_refresh_cookie(response, pair)
    return pair


@auth.post("/google", response_model=TokenPair)
async def google_login(body: GoogleLogin, session: Session):
    user = await service.login_with_google(session, body.id_token)
    pair = await service.issue_tokens(session, user)
    await session.commit()
    return pair


@auth.post("/telegram/webapp", response_model=TokenPair)
async def telegram_webapp(body: TelegramWebAppLogin, session: Session):
    token = get_settings().main_bot_token
    if body.store_id:
        st = await session.get(Store, body.store_id)
        if st and st.bot_token_enc:
            token = decrypt(st.bot_token_enc)
    if not token:
        raise AppError("TELEGRAM_DISABLED", "Telegram پیکربندی نشده است.", 400)
    tg = service.verify_telegram_webapp(body.init_data, token)
    from melorin.modules.identity.schemas import TelegramProfile

    user, created = await service.login_with_telegram(session, TelegramProfile(telegram_id=tg["id"], first_name=tg.get("first_name"), last_name=tg.get("last_name"), username=tg.get("username")))
    await _after_signup(session, user, created, body.store_id, None)
    pair = await service.issue_tokens(session, user)
    await session.commit()
    return pair


@auth.post("/telegram/bot", response_model=TokenPair, dependencies=[Depends(require_bot_service)])
async def telegram_bot_login(body: TelegramBotLogin, session: Session):
    """Trusted bot runner exchanges a Telegram user (validated by Telegram itself) for a Core session."""
    user, created = await service.login_with_telegram(session, body)
    await _after_signup(session, user, created, body.store_id, body.referral_code)
    pair = await service.issue_tokens(session, user, ua="telegram-bot")
    await session.commit()
    return pair


@auth.post("/telegram/link", response_model=TokenPair, dependencies=[Depends(require_bot_service)])
async def telegram_link(body: TelegramLink, session: Session):
    user = await service.link_telegram(session, body.code, body)
    pair = await service.issue_tokens(session, user, ua="telegram-bot")
    await session.commit()
    return pair


@auth.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, request: Request, response: Response, session: Session):
    raw = body.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise AppError("INVALID_REFRESH", "نشست نامعتبر است.", 401)
    pair = await service.rotate_refresh(session, raw)
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
        id=u.id, display_name=u.display_name, email=u.email, is_admin=u.is_super_admin, is_guest=u.is_guest,
        totp_enabled=u.totp_enabled, referral_code=u.referral_code,
        identities=[IdentityOut(id=i.id, provider=i.provider, subject=i.subject if i.provider != "telegram" else i.subject, verified=i.verified_at is not None) for i in u.identities],
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
async def my_stores(user: CurrentUser, session: Session):
    rows = (await session.execute(select(Store, StoreMembership).join(StoreMembership, StoreMembership.store_id == Store.id).where(StoreMembership.user_id == user.id))).all()
    return [{"id": s.id, "name": s.name, "kind": s.kind, "slug": s.slug, "role": m.role} for s, m in rows]


@me.post("/link-codes/telegram", response_model=LinkCodeOut)
async def create_telegram_link_code(user: CurrentUser, session: Session):
    code = await service.create_link_code(session, user)
    store = await main_store(session)
    link = f"https://t.me/{store.bot_username}?start=link_{code}" if store.bot_username else None
    return LinkCodeOut(code=code, expires_in=600, telegram_deeplink=link)


@me.post("/identities/email")
async def attach_email(body: EmailCodeVerify, user: CurrentUser, session: Session):
    await service.attach_email(session, user, body.email, body.code)
    return {"ok": True}


@auth.post("/admin/password")
async def change_admin_password(body: AdminPasswordChange, admin: CurrentUser, session: Session):
    if not admin.is_super_admin:
        raise AppError("FORBIDDEN", "فقط ادمین می‌تواند رمز این حساب را تغییر دهد.", 403)
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
