"""Authentication, authorization and StoreContext resolution. Enforced in Core, never trusted from UI."""
import hmac
import ipaddress
import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, integrations
from melorin.core.config import get_settings
from melorin.core.context import client_ip
from melorin.core.db import get_session
from melorin.core.errors import AppError, Forbidden
from melorin.core.security import decode_access_token
from melorin.modules.identity.models import User
from melorin.modules.stores.models import Store, StoreMembership

bearer = HTTPBearer(auto_error=False)
Session = Annotated[AsyncSession, Depends(get_session)]


async def optional_user(
    session: Session, creds: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> User | None:
    if not creds:
        return None
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise AppError("UNAUTHORIZED", "نشست نامعتبر یا منقضی است.", 401) from None
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise AppError("UNAUTHORIZED", "حساب کاربری غیرفعال است.", 401)
    return user


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


async def require_bot_service(x_bot_secret: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_bot_secret, get_settings().bot_service_secret):
        raise AppError("UNAUTHORIZED", "invalid bot credentials", 401)


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(require_admin)]


@dataclass
class StoreContext:
    store: Store
    user: User
    membership: StoreMembership | None

    @property
    def is_admin(self) -> bool:
        return self.user.is_super_admin

    @property
    def is_owner(self) -> bool:
        return self.store.owner_user_id == self.user.id


async def main_store(session: AsyncSession) -> Store:
    store = await session.scalar(select(Store).where(Store.kind == "main"))
    if not store:
        raise AppError("MAIN_STORE_MISSING", "فروشگاه اصلی پیکربندی نشده است.", 500)
    return store


async def resolve_store_context(session: AsyncSession, store_id: uuid.UUID, user: User) -> StoreContext:
    store = await session.get(Store, store_id)
    if not store:
        raise AppError("NOT_FOUND", "فروشگاه یافت نشد.", 404)
    if store.status != "active" and not user.is_super_admin and store.owner_user_id != user.id:
        raise AppError("STORE_SUSPENDED", "این فروشگاه موقتاً غیرفعال است.", 403)
    m = await session.scalar(
        select(StoreMembership).where(StoreMembership.store_id == store.id, StoreMembership.user_id == user.id)
    )
    if m is None:
        # Joining a store is implicit on first use (customer). Identity stays central.
        m = StoreMembership(store_id=store.id, user_id=user.id, role="owner" if store.owner_user_id == user.id else "customer")
        session.add(m)
        await session.commit()
    elif m.status != "active":
        audit.security_event(session, "blocked_member_access", user.id, {"store_id": str(store.id)})
        await session.commit()
        raise AppError("MEMBERSHIP_BLOCKED", "دسترسی شما به این فروشگاه مسدود است.", 403)
    return StoreContext(store=store, user=user, membership=m)


async def store_context(session: Session, user: CurrentUser, store_id: uuid.UUID = Path(...)) -> StoreContext:
    return await resolve_store_context(session, store_id, user)


async def owned_store_context(ctx: Annotated[StoreContext, Depends(store_context)]) -> StoreContext:
    if not (ctx.is_owner or ctx.is_admin) or ctx.store.kind != "reseller":
        raise Forbidden()
    return ctx


StoreCtx = Annotated[StoreContext, Depends(store_context)]
OwnerCtx = Annotated[StoreContext, Depends(owned_store_context)]
