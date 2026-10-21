"""HTTP surface of "Login with Telegram" (OpenID Connect redirect flow) plus the public button config.

``start`` and ``callback`` are top-level browser navigations, so every outcome - success or failure - ends in a redirect
back to the storefront (``/#/dashboard`` or ``/?tg_error=<reason>``) instead of a JSON page.
"""

import secrets
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse

from melorin.core import audit, channel, flags, integrations
from melorin.core.config import get_settings
from melorin.core.deps import Session
from melorin.core.errors import AppError
from melorin.core.ratelimit import RateLimit
from melorin.modules.identity import service
from melorin.modules.identity import telegram_oidc as oidc
from melorin.modules.identity.router import _set_refresh_cookie
from melorin.kernel.models.stores import Store

tgoidc = APIRouter(prefix="/auth/telegram", tags=["auth"])
NO_STORE = {"Cache-Control": "no-store"}


def _back(origin: str, reason: str | None = None) -> RedirectResponse:
    """303 to the storefront; always clears the one-shot flow cookie."""
    target = f"{origin}/#/dashboard" if reason is None else f"{origin}/?{urlencode({'tg_error': reason})}"
    resp = RedirectResponse(target, status_code=303, headers=NO_STORE)
    resp.delete_cookie(oidc.COOKIE, path=oidc.COOKIE_PATH)
    return resp


@tgoidc.get("/config")
async def config(session: Session, response: Response):
    """Public: which Telegram login buttons the storefront should draw (no Client ID, no secret)."""
    response.headers.update(NO_STORE)
    return integrations.public_telegram(await integrations.get_telegram(session))


@tgoidc.get("/oidc/start", dependencies=[Depends(RateLimit("tgoidc-start", 20, 60))])
async def start(session: Session, request: Request, store_id: uuid.UUID | None = None):
    cfg = await integrations.get_telegram(session)
    fallback = oidc.callback_origin(None)
    if not integrations.telegram_oidc_ready(cfg):
        return _back(fallback, "unavailable")
    try:
        site = await channel.site_channel(session, request, hint=store_id)  # Host decides; ``store_id`` can only agree
    except AppError:
        return _back(fallback, "unavailable")
    store = await session.get(Store, site.store_id)
    if store is None or store.status != "active":
        return _back(fallback, "unavailable")
    origin = oidc.callback_origin(store)
    if not get_settings().is_dev and (request.headers.get("host") or "").lower() != origin.split("://", 1)[1]:
        # The state cookie would be set on one host and Telegram would return the browser to another.
        return _back(fallback, "origin_mismatch")
    if not await flags.is_enabled(session, "bot", store_id=store.id, channel="telegram"):
        return _back(origin, "unavailable")
    url, sealed = oidc.new_flow(cfg["client_id"], store.id, origin)
    resp = RedirectResponse(url, status_code=303, headers=NO_STORE)
    resp.set_cookie(
        oidc.COOKIE,
        sealed,
        max_age=oidc.FLOW_TTL_SECONDS,
        httponly=True,
        secure=not get_settings().is_dev,
        samesite="lax",
        path=oidc.COOKIE_PATH,
    )
    return resp


@tgoidc.get("/oidc/callback", dependencies=[Depends(RateLimit("tgoidc-callback", 30, 60))])
async def callback(session: Session, request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    flow = oidc.unseal(request.cookies.get(oidc.COOKIE))
    if flow is None:
        return _back(oidc.callback_origin(None), "session_expired")
    origin = flow["org"]
    if error or not code or not state:
        return _back(origin, "user_denied" if error == "access_denied" else "failed")
    if not secrets.compare_digest(state, flow["state"]):
        audit.security_event(session, "tg_oidc_state_mismatch", None, {})
        await session.commit()
        return _back(origin, "failed")
    cfg = await integrations.get_telegram(session)
    store = await session.get(Store, uuid.UUID(flow["sid"]))
    if not integrations.telegram_oidc_ready(cfg) or store is None or store.status != "active":
        return _back(origin, "unavailable")
    try:
        id_token = await oidc.exchange_code(cfg["client_id"], integrations.telegram_client_secret(cfg), code, flow["ru"], flow["cv"])
        claims = await oidc.verify_id_token(id_token, cfg["client_id"], flow["nonce"])
        profile = oidc.profile_from_claims(claims)
    except AppError as exc:
        audit.security_event(session, "tg_oidc_rejected", None, {"code": exc.code, **(exc.details or {})})
        await session.commit()
        reason = {"TELEGRAM_OIDC_UNREACHABLE": "unreachable", "TELEGRAM_OIDC_CLIENT_REJECTED": "unavailable"}.get(exc.code, "failed")
        return _back(origin, reason)

    # Same business rules as the bot-approval flow (identity/telegram_web.py :: decide).
    if not await flags.is_enabled(session, "bot", store_id=store.id, channel="telegram"):
        return _back(origin, "unavailable")
    known = await service.find_identity(session, "telegram", str(profile.telegram_id))
    if known is None and not await flags.is_enabled(session, "registration"):
        return _back(origin, "registration_closed")
    user, _created = await service.login_with_telegram(session, profile)
    if not user.is_active:
        audit.security_event(session, "tg_oidc_inactive_account", user.id, {})
        await session.commit()
        return _back(origin, "account_disabled")
    if user.is_super_admin:
        audit.security_event(session, "tg_oidc_admin_refused", user.id, {})
        await session.commit()
        return _back(origin, "admin_use_panel")
    try:
        site = await channel.site_channel(session, request, hint=store.id)  # the callback lands on the store's own host
    except AppError:
        return _back(origin, "origin_mismatch")
    pair = await service.issue_tokens(session, user, site, ua=request.headers.get("user-agent"))
    audit.record(session, "tg_oidc_login.approved", actor_id=user.id, entity_type="user", entity_id=user.id, store_id=store.id)
    await session.commit()
    resp = _back(origin)
    _set_refresh_cookie(resp, pair)
    return resp
