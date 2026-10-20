"""HTTP surface of the "login to the website with the Telegram bot" flow (docs/TELEGRAM-WEB-LOGIN.md).

Browser endpoints are public but rate limited; bot endpoints require the shared bot secret and are additionally
scoped to the store the calling bot serves.
"""

import datetime as dt

from fastapi import APIRouter, Depends, Request, Response

from melorin.core import channel, integrations
from melorin.core.db import utcnow
from melorin.core.deps import BotAuth, Session, main_store, require_bot_service
from melorin.core.errors import AppError
from melorin.core.ratelimit import RateLimit, client_ip
from melorin.modules.identity import telegram_web as web
from melorin.modules.identity.router import _set_refresh_cookie
from melorin.modules.identity.schemas import (
    TelegramProfile,
    TelegramWebDecision,
    TelegramWebDecisionOut,
    TelegramWebInspect,
    TelegramWebInspectOut,
    TelegramWebPoll,
    TelegramWebPollOut,
    TelegramWebStart,
    TelegramWebStartOut,
)
from melorin.modules.stores.models import Store

tgweb = APIRouter(prefix="/auth/telegram/web", tags=["auth"])
NO_STORE = {"Cache-Control": "no-store"}


def _qr(link: str) -> str | None:
    """Server-rendered QR as an inert ``data:`` image (no client dependency, nothing to inject). Optional."""
    try:
        import segno
    except ImportError:
        return None
    return segno.make(link, error="m").svg_data_uri(scale=6, border=2, dark="#10233f", light="#ffffff")


# ---------------- browser ----------------
@tgweb.post("/sessions", response_model=TelegramWebStartOut, dependencies=[Depends(RateLimit("tgweb-start", 10, 60))])
async def start(body: TelegramWebStart, session: Session, request: Request, response: Response):
    site = await channel.site_channel(session, request, hint=body.store_id)  # Host decides; the id can only agree with it
    store = await session.get(Store, site.store_id)
    if store is None:
        raise AppError("NOT_FOUND", "فروشگاه یافت نشد.", 404)
    started = await web.create_session(session, store, ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    link = f"https://t.me/{started.bot_username}?start=wl_{started.row.public_id}"
    cfg = await integrations.get_telegram(session)
    response.headers.update(NO_STORE)
    return TelegramWebStartOut(
        session_id=started.row.public_id,
        poll_token=started.poll_token,
        deeplink=link,
        qr=_qr(link),
        match_code=started.row.match_code if web.number_match_enabled(cfg) else None,
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
    return TelegramWebPollOut(status=result.status, reason=result.reason, expires_in=result.expires_in, tokens=result.tokens)


@tgweb.post("/sessions/{session_id}/cancel", dependencies=[Depends(RateLimit("tgweb-cancel", 30, 60))])
async def cancel(session_id: str, body: TelegramWebPoll, session: Session):
    await web.cancel(session, session_id, body.poll_token)
    return {"ok": True}


# ---------------- bot runner (X-Bot-Secret) ----------------
@tgweb.post("/bot/inspect", response_model=TelegramWebInspectOut)
async def bot_inspect(body: TelegramWebInspect, session: Session, bot: BotAuth):
    await channel.bot_channel(session, bot, body.store_id)  # this runner may serve that store
    row = await web.inspect(session, body.session_id, body.store_id, body.telegram_id)
    created = row.created_at.replace(tzinfo=row.created_at.tzinfo or dt.UTC)
    number_match = web.number_match_enabled(await integrations.get_telegram(session))
    return TelegramWebInspectOut(
        status=row.status,
        device=row.req_device or "دستگاه ناشناس",
        ip=row.req_ip,
        age_seconds=max(0, int((utcnow() - created).total_seconds())),
        expires_in=web.seconds_left(row),
        number_match=number_match,
        choices=web.choices_of(row) if number_match else [],
    )


@tgweb.post("/bot/decide", response_model=TelegramWebDecisionOut)
async def bot_decide(body: TelegramWebDecision, session: Session, bot: BotAuth):
    await channel.bot_channel(session, bot, body.store_id)
    profile = TelegramProfile(**body.model_dump(include=set(TelegramProfile.model_fields)))
    return TelegramWebDecisionOut(**await web.decide(session, body.session_id, body.store_id, profile, body.action, body.choice))
