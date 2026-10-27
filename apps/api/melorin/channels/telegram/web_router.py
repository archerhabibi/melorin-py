"""HTTP surface of the "login to the website with the Telegram bot" flow (docs/TELEGRAM-WEB-LOGIN.md).

Browser endpoints are public but rate limited; bot endpoints require the shared bot secret and are additionally
scoped to the store the calling bot serves.
"""

import datetime as dt

from fastapi import APIRouter, Depends, Request, Response

from melorin.core import channel, integrations
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.core.deps import BotAuth, Session
from melorin.core.errors import AppError
from melorin.core.ratelimit import RateLimit, client_ip
from melorin.core.security import new_opaque_token
from melorin.channels.telegram import trust, web
from melorin.modules.identity.router import _set_refresh_cookie
from melorin.modules.identity.schemas import (
    TelegramProfile,
    TelegramWebDecision,
    TelegramWebDecisionOut,
    TelegramWebDevices,
    TelegramWebDevicesOut,
    TelegramWebForget,
    TelegramWebInspect,
    TelegramWebInspectOut,
    TelegramWebPoll,
    TelegramWebPollOut,
    TelegramWebRevoke,
    TelegramWebRevokeOut,
    TelegramWebStart,
    TelegramWebStartOut,
)
from melorin.kernel.models.stores import Store

tgweb = APIRouter(prefix="/auth/telegram/web", tags=["auth"])
NO_STORE = {"Cache-Control": "no-store"}


def _qr(link: str) -> str | None:
    """Server-rendered QR as an inert ``data:`` image (no client dependency, nothing to inject). Optional."""
    try:
        import segno
    except ImportError:
        return None
    return segno.make(link, error="m").svg_data_uri(scale=6, border=2, dark="#10233f", light="#ffffff")


# ---------------- trusted-device cookie ----------------
# The device key lives in an HttpOnly cookie minted by the server: page scripts (and so any XSS) can never read it, and the
# storefront code keeps nothing in browser storage. Only the SHA-256 of the key is stored in the database.
DEVICE_COOKIE = "melorin_dk"
DEVICE_COOKIE_PATH = "/api/v1/auth/telegram/web"


def _device_key(request: Request, body_key: str | None = None) -> str | None:
    """The browser's key: the cookie wins; a well-formed body key is accepted for non-browser clients."""
    for candidate in (request.cookies.get(DEVICE_COOKIE), body_key):
        if trust.key_hash_of(candidate):
            return candidate
    return None


def _set_device_cookie(response: Response, key: str) -> None:
    response.set_cookie(
        DEVICE_COOKIE,
        key,
        httponly=True,
        secure=not get_settings().is_dev,
        samesite="lax",
        max_age=max(1, trust.trust_days()) * 86400,
        path=DEVICE_COOKIE_PATH,
    )


# ---------------- browser ----------------
@tgweb.post("/sessions", response_model=TelegramWebStartOut, dependencies=[Depends(RateLimit("tgweb-start", 10, 60))])
async def start(body: TelegramWebStart, session: Session, request: Request, response: Response):
    site = await channel.site_channel(session, request, hint=body.store_id)  # Host decides; the id can only agree with it
    store = await session.get(Store, site.store_id)
    if store is None:
        raise AppError("NOT_FOUND", "فروشگاه یافت نشد.", 404)
    key = _device_key(request, body.device_key) or new_opaque_token(32)
    if trust.trust_days() > 0 and body.remember:
        _set_device_cookie(response, key)  # refreshed on every visit; trust itself is only granted after an approval
    started = await web.create_session(
        session,
        store,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        device_key=key,
        remember=body.remember,
    )
    link = f"https://t.me/{started.bot_username}?start=wl_{started.row.public_id}"
    cfg = await integrations.get_telegram(session)
    response.headers.update(NO_STORE)
    return TelegramWebStartOut(
        session_id=started.row.public_id,
        poll_token=started.poll_token,
        deeplink=link,
        qr=_qr(link),
        # A trusted browser is never shown a number: there is nothing to match (silent) or the bot link is the approval (auto).
        match_code=started.row.match_code if started.level == "manual" and web.number_match_enabled(cfg) else None,
        level=started.level,
        bot_username=started.bot_username,
        expires_in=web.seconds_left(started.row),
        poll_interval=web.POLL_INTERVAL_SECONDS,
    )


@tgweb.post("/sessions/{session_id}/poll", response_model=TelegramWebPollOut, dependencies=[Depends(RateLimit("tgweb-poll", 120, 60))])
async def poll(session_id: str, body: TelegramWebPoll, session: Session, request: Request, response: Response):
    result = await web.poll(session, session_id, body.poll_token, request, user_agent=request.headers.get("user-agent"))
    response.headers.update(NO_STORE)
    if result.tokens:
        _set_refresh_cookie(response, result.tokens)
    return TelegramWebPollOut(
        status=result.status,
        reason=result.reason,
        expires_in=result.expires_in,
        tokens=result.tokens,
        level=result.level,
        match_code=result.match_code,
    )


@tgweb.post("/sessions/{session_id}/cancel", dependencies=[Depends(RateLimit("tgweb-cancel", 30, 60))])
async def cancel(session_id: str, body: TelegramWebPoll, session: Session):
    await web.cancel(session, session_id, body.poll_token)
    return {"ok": True}


@tgweb.post("/devices/forget", dependencies=[Depends(RateLimit("tgweb-forget", 30, 60))])
async def forget_device(request: Request, session: Session, response: Response, body: TelegramWebForget | None = None):
    """The browser drops its own trust (sign-out on a shared computer). Holding the device key is the proof."""
    response.headers.update(NO_STORE)
    key = _device_key(request, body.device_key if body else None)
    response.delete_cookie(DEVICE_COOKIE, path=DEVICE_COOKIE_PATH)
    return {"revoked": await web.forget_device(session, key) if key else 0}


# ---------------- bot runner (X-Bot-Secret) ----------------
@tgweb.post("/bot/inspect", response_model=TelegramWebInspectOut)
async def bot_inspect(body: TelegramWebInspect, session: Session, bot: BotAuth):
    await channel.bot_channel(session, bot, body.store_id)  # this runner may serve that store
    profile = TelegramProfile(**body.model_dump(include=set(TelegramProfile.model_fields)))
    row = await web.inspect(session, body.session_id, body.store_id, body.telegram_id, profile=profile)
    created = row.created_at.replace(tzinfo=row.created_at.tzinfo or dt.UTC)
    number_match = web.number_match_enabled(await integrations.get_telegram(session))
    return TelegramWebInspectOut(
        status=row.status,
        device=row.req_device or "دستگاه ناشناس",
        ip=row.req_ip,
        age_seconds=max(0, int((utcnow() - created).total_seconds())),
        expires_in=web.seconds_left(row),
        number_match=number_match,
        choices=web.choices_of(row) if number_match and row.status == "scanned" else [],
        auto_approved=row.status == "approved",
        auto_reason=row.deny_reason if row.status == "denied" else None,
    )


@tgweb.post("/bot/decide", response_model=TelegramWebDecisionOut)
async def bot_decide(body: TelegramWebDecision, session: Session, bot: BotAuth):
    await channel.bot_channel(session, bot, body.store_id)
    profile = TelegramProfile(**body.model_dump(include=set(TelegramProfile.model_fields)))
    return TelegramWebDecisionOut(**await web.decide(session, body.session_id, body.store_id, profile, body.action, body.choice))


@tgweb.post("/bot/devices", response_model=TelegramWebDevicesOut)
async def bot_devices(body: TelegramWebDevices, session: Session, bot: BotAuth):
    """Trusted browsers of the calling Telegram account in this store (the bot's /devices screen)."""
    await channel.bot_channel(session, bot, body.store_id)
    return TelegramWebDevicesOut(devices=await web.list_devices(session, body.store_id, body.telegram_id))


@tgweb.post("/bot/revoke", response_model=TelegramWebRevokeOut)
async def bot_revoke(body: TelegramWebRevoke, session: Session, bot: BotAuth):
    """ "This was not me" / remove one device. A Telegram account can only ever revoke its own devices."""
    await channel.bot_channel(session, bot, body.store_id)
    return TelegramWebRevokeOut(revoked=await web.revoke_devices(session, body.store_id, body.telegram_id, body.device_id))
