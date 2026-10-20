"""Authentication, authorization and StoreContext resolution. Enforced in Core, never trusted from UI."""

import ipaddress
import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, channel, integrations
from melorin.core.channel import BotService, SessionClaims
from melorin.core.context import client_ip
from melorin.core.db import get_session
from melorin.core.errors import AppError, Forbidden
from melorin.core.security import decode_access_token
from melorin.modules.identity.models import User
from melorin.modules.stores.models import Store, StoreMembership

bearer = HTTPBearer(auto_error=False)
Session = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class AuthSession:
    """A verified access token: the user (from the database) plus the channel binding the token carries."""

    user: User
    claims: SessionClaims

    @property
    def is_admin_session(self) -> bool:
        """Admin rights need BOTH the user flag and an admin-channel session (password+TOTP login of the admin panel)."""
        return self.claims.is_admin and self.user.is_super_admin


async def auth_session(session: Session, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> AuthSession | None:
    if not creds:
        return None
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise AppError("UNAUTHORIZED", "نشست نامعتبر یا منقضی است.", 401) from None
    claims = SessionClaims.from_payload(payload)  # a token without a channel binding is refused (SESSION_UNBOUND)
    user = await session.get(User, claims.user_id)
    if not user or not user.is_active:
        raise AppError("UNAUTHORIZED", "حساب کاربری غیرفعال است.", 401)
    if claims.is_admin and not user.is_super_admin:  # demoted since the token was issued
        raise AppError("UNAUTHORIZED", "نشست نامعتبر یا منقضی است.", 401)
    return AuthSession(user=user, claims=claims)


async def current_auth(auth: AuthSession | None = Depends(auth_session)) -> AuthSession:
    if auth is None:
        raise AppError("UNAUTHORIZED", "ابتدا وارد شوید.", 401)
    return auth


async def optional_user(auth: AuthSession | None = Depends(auth_session)) -> User | None:
    return auth.user if auth else None


async def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise AppError("UNAUTHORIZED", "ابتدا وارد شوید.", 401)
    return user


async def require_admin(session: Session, user: User = Depends(current_user)) -> User:
    if not user.is_super_admin:
        raise Forbidden()
    if not user.totp_enabled:
        raise AppError("ADMIN_2FA_REQUIRED", "فعال‌سازی احراز هویت دومرحله‌ای برای ادمین الزامی است.", 403)
    if user.allowed_ips and client_ip.get() not in user.allowed_ips:
        raise AppError("IP_NOT_ALLOWED", "دسترسی از این IP مجاز نیست.", 403)
    # Optional global allowlist, configured in the admin panel (Settings -> Integrations). OFF by default.
    access = await integrations.get_admin_access(session)
    if access.get("enabled") and access.get("ips") and not ip_allowed(client_ip.get(), access["ips"]):
        raise AppError("ADMIN_IP_NOT_ALLOWED", "دسترسی ادمین از این IP مجاز نیست.", 403)
    return user


def ip_allowed(ip: str | None, networks: list[str]) -> bool:
    """Fail closed: an unresolvable peer ("?", unix socket, ...) is never allowed."""
    try:
        addr = ipaddress.ip_address(ip or "")
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(n, strict=False) for n in networks)


async def require_admin_session(auth: AuthSession = Depends(current_auth), user: User = Depends(require_admin)) -> User:
    """Admin API: the user must be an admin AND the session must come from the admin panel's own login (password + TOTP).

    A session opened through a bot, a store website or an email code is a CUSTOMER session even when the account behind it
    happens to be an admin, so it can never reach ``/admin/*``.
    """
    if not auth.is_admin_session:
        raise Forbidden()
    return user


async def require_bot_service(x_bot_secret: str = Header(default="")) -> BotService:
    bot = channel.identify_bot(x_bot_secret)
    if bot is None:
        raise AppError("UNAUTHORIZED", "invalid bot credentials", 401)
    return bot


CurrentUser = Annotated[User, Depends(current_user)]
CurrentAuth = Annotated[AuthSession, Depends(current_auth)]
AdminUser = Annotated[User, Depends(require_admin_session)]
BotAuth = Annotated[BotService, Depends(require_bot_service)]


@dataclass
class StoreContext:
    store: Store
    user: User
    membership: StoreMembership | None
    # True only for an admin-panel session of an admin user. A customer session of the same account is NOT an admin here.
    admin_session: bool = False

    @property
    def is_admin(self) -> bool:
        return self.admin_session and self.user.is_super_admin

    @property
    def is_owner(self) -> bool:
        return self.store.owner_user_id == self.user.id


async def main_store(session: AsyncSession) -> Store:
    store = await session.scalar(select(Store).where(Store.kind == "main"))
    if not store:
        raise AppError("MAIN_STORE_MISSING", "فروشگاه اصلی پیکربندی نشده است.", 500)
    return store


async def resolve_store_context(session: AsyncSession, store_id: uuid.UUID, user: User, *, admin_session: bool = False) -> StoreContext:
    store = await session.get(Store, store_id)
    if not store:
        raise AppError("NOT_FOUND", "فروشگاه یافت نشد.", 404)
    if store.status != "active" and not (admin_session and user.is_super_admin) and store.owner_user_id != user.id:
        raise AppError("STORE_SUSPENDED", "این فروشگاه موقتاً غیرفعال است.", 403)
    m = await session.scalar(select(StoreMembership).where(StoreMembership.store_id == store.id, StoreMembership.user_id == user.id))
    if m is None:
        # Joining a store is implicit on first use (customer). Identity stays central.
        m = StoreMembership(store_id=store.id, user_id=user.id, role="owner" if store.owner_user_id == user.id else "customer")
        session.add(m)
        await session.commit()
    elif m.status != "active":
        audit.security_event(session, "blocked_member_access", user.id, {"store_id": str(store.id)})
        await session.commit()
        raise AppError("MEMBERSHIP_BLOCKED", "دسترسی شما به این فروشگاه مسدود است.", 403)
    return StoreContext(store=store, user=user, membership=m, admin_session=admin_session)


async def store_context(session: Session, auth: CurrentAuth, store_id: uuid.UUID = Path(...)) -> StoreContext:
    """Customer plane. The session must have been opened for THIS store (checked before any query), then the usual
    membership / suspension rules apply."""
    channel.ensure_store(auth.claims, store_id)
    return await resolve_store_context(session, store_id, auth.user, admin_session=auth.is_admin_session)


async def owner_store_context(session: Session, auth: CurrentAuth, store_id: uuid.UUID = Path(...)) -> StoreContext:
    """Owner plane (reseller panel): the store's own sessions, or the main store as account hub for the store's real owner."""
    await channel.ensure_owner_store(session, auth.claims, auth.user.id, store_id)
    return await resolve_store_context(session, store_id, auth.user, admin_session=auth.is_admin_session)


async def owned_store_context(ctx: Annotated[StoreContext, Depends(owner_store_context)]) -> StoreContext:
    if not (ctx.is_owner or ctx.is_admin) or ctx.store.kind != "reseller":
        raise Forbidden()
    return ctx


StoreCtx = Annotated[StoreContext, Depends(store_context)]
OwnerCtx = Annotated[StoreContext, Depends(owned_store_context)]
