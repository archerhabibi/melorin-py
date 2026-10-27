"""Shared by the identity route families: cookie names and helpers for the refresh/nonce cookies and sign-up side effects."""

from fastapi import Response
from sqlalchemy import select
from melorin.core.config import get_settings
from melorin.core.deps import main_store
from melorin.core.errors import AppError
from melorin.modules.identity import service
from melorin.kernel.models.identity import User
from melorin.modules.identity.schemas import (
    TokenPair,
)
from melorin.modules.referral import service as referral
from melorin.kernel.models.stores import Store, StoreMembership


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
    """Attach the sign-up (and its referral) to the store of the CHANNEL the user came through, never to a client-sent id.

    Referral is per store: it counts when the person is NEW TO THIS STORE (a brand-new account, or an existing account joining
    this store for the first time). Someone who is already a member of the store is never re-attributed by a later link.
    """
    if not ref_code or user.is_super_admin:
        return
    store = await session.get(Store, store_id) if store_id else await main_store(session)
    if not store:
        return
    if not created:
        member = await session.scalar(select(StoreMembership.id).where(StoreMembership.store_id == store.id, StoreMembership.user_id == user.id))
        if member:
            return
    referrer = await service.user_by_referral_code(session, ref_code)
    await referral.attach(session, store.id, user, referrer)


def _refuse_admin_on_customer_channel(user: User) -> None:
    """Admins sign in only at the admin panel (password + TOTP): email codes, store sites and bots never mint admin sessions."""
    if user.is_super_admin:
        raise AppError("ADMIN_USE_PANEL", "ورود مدیران فقط از پنل مدیریت انجام می‌شود.", 403)
