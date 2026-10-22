"""/me: profile, visible stores, account linking (Telegram/Google/e-mail), password and TOTP management."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from melorin.core import audit, channel
from melorin.core.crypto import decrypt, encrypt
from melorin.core.config import get_settings
from melorin.core.deps import AdminUser, CurrentAuth, CurrentUser, Session, main_store
from melorin.core.errors import AppError
from melorin.core.ratelimit import hit
from melorin.core.security import totp_counter, totp_new_secret, verify_password, hash_password
from melorin.modules.identity import google as google_signin, service
from melorin.kernel.models.identity import User
from melorin.modules.identity.schemas import (
    AdminPasswordChange,
    EmailCodeVerify,
    GoogleLink,
    IdentityOut,
    LinkCodeOut,
    MeOut,
    MeUpdate,
    SetPassword,
    TotpEnable,
    TotpSetupOut,
    WebHandoffIn,
    WebHandoffOut,
)
from melorin.kernel.models.stores import Store, StoreMembership
from melorin.modules.identity.routes._common import GOOGLE_NONCE_COOKIE, GOOGLE_NONCE_PATH
from melorin.modules.identity.routes.sign_in import auth


me = APIRouter(prefix="/me", tags=["me"])


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
    await google_signin.link_google(session, user, body.id_token, cookies.get(GOOGLE_NONCE_COOKIE))
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
