"""Mandatory channel membership of the main Telegram bot: config access, the membership check and the admin probe.

Where it is enforced: ``POST /auth/telegram/bot`` (``modules/identity/routes/sign_in.py``). The bot runner exchanges every
update for a Core session there, so refusing that exchange with ``CHANNEL_JOIN_REQUIRED`` gates the whole bot while the
runner stays transport only (it just renders the join screen). Reseller bots are never gated: their stores have their own
audience and their bot is not an admin of the main store's channels.

Failure policy (fail-open, deliberately): a channel the bot cannot read (not an admin, channel deleted, wrong id) or a
Telegram outage must not lock every customer out of the store. Such a channel is skipped, logged and counted
(``channel_join_check_failed_total``); the admin sees the problem with the panel's "check" button. A definite answer -
``left`` / ``kicked`` - always refuses.

Positive answers are remembered for ``cache_seconds`` per (user, set of channels) so a busy chat does not call
``getChatMember`` on every message; negative answers are never cached, so "✅ I joined" is honoured at once.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.channels.telegram.bot_api import TelegramApiError, TelegramChannel
from melorin.core import integrations, settings_store
from melorin.core.channel import Channel
from melorin.core.config import get_settings
from melorin.core.crypto import decrypt
from melorin.core.errors import AppError
from melorin.core.metrics import inc
from melorin.domain import channel_join as cj
from melorin.kernel.models.stores import Store

log = logging.getLogger("melorin.channel_gate")

CACHE_MAX_ENTRIES = 20_000
_member_cache: dict[tuple[int, str], float] = {}  # (telegram id, channels fingerprint) -> monotonic expiry


# ------------------------------------------------------------------------------------------------ config
async def load(session: AsyncSession) -> dict[str, Any]:
    return cj.stored(await settings_store.get(session, integrations.CHANNEL_JOIN_KEY))


async def save(session: AsyncSession, cfg: dict[str, Any]) -> None:
    await integrations.save(session, integrations.CHANNEL_JOIN_KEY, cfg)
    clear_cache()  # this process at once; other processes are covered by the fingerprint / their short TTL


async def main_bot_token(session: AsyncSession) -> str:
    """The main store's bot token (encrypted on the store row; the environment token is the fallback). Never logged."""
    main = await session.scalar(select(Store).where(Store.kind == "main"))
    return (decrypt(main.bot_token_enc) if main and main.bot_token_enc else "") or get_settings().main_bot_token or ""


def _channel(token: str) -> TelegramChannel:
    return TelegramChannel(token=token, core_base_url="http://core.invalid", channel="main", timeout=8.0)


# ------------------------------------------------------------------------------------------------ cache
def clear_cache() -> None:
    _member_cache.clear()


def _cached(key: tuple[int, str]) -> bool:
    expiry = _member_cache.get(key)
    if expiry is None:
        return False
    if expiry <= time.monotonic():
        _member_cache.pop(key, None)
        return False
    return True


def _remember(key: tuple[int, str], seconds: int) -> None:
    if seconds <= 0:
        return
    now = time.monotonic()
    if len(_member_cache) >= CACHE_MAX_ENTRIES:
        for k in [k for k, exp in _member_cache.items() if exp <= now] or list(_member_cache)[: CACHE_MAX_ENTRIES // 10]:
            _member_cache.pop(k, None)
    _member_cache[key] = now + seconds


# ------------------------------------------------------------------------------------------------ enforcement
def applies_to(chan: Channel) -> bool:
    """Only the main store's bot is gated."""
    return chan.kind == "bot" and chan.store_kind == "main"


async def _joined(tg: TelegramChannel, chat: str, telegram_id: int) -> bool:
    """True / False for a definite answer; True (fail-open) when Telegram cannot tell us."""
    try:
        member = await tg.get_chat_member(chat, telegram_id)
    except TelegramApiError as exc:
        reason = (exc.description or "").lower()
        if exc.code == 400 and ("user not found" in reason or "participant_id_invalid" in reason):
            return False  # Telegram does not know this user in that chat: certainly not a member
        inc("channel_join_check_failed_total", reason="permanent" if exc.permanent else "transient")
        log.warning("channel join check skipped for %s: telegram %s %s", chat, exc.code, exc.description[:120])
        return True
    return cj.is_member(member)


async def missing_channels(session: AsyncSession, chan: Channel, telegram_id: int) -> list[dict[str, str]]:
    """The channels (public projection) this bot user still has to join; empty when the gate is off or satisfied."""
    if not applies_to(chan):
        return []
    cfg = await load(session)
    if not cfg["enabled"] or not cfg["channels"]:
        return []
    key = (int(telegram_id), cj.fingerprint(cfg))
    if _cached(key):
        return []
    token = await main_bot_token(session)
    if not token:
        log.warning("channel join is enabled but the main bot has no token; gate skipped")
        return []
    tg = _channel(token)
    answers = await asyncio.gather(*(_joined(tg, ch["chat"], int(telegram_id)) for ch in cfg["channels"]))
    missing = [cj.public_channel(ch) for ch, ok in zip(cfg["channels"], answers, strict=True) if not ok]
    if missing:
        inc("channel_join_refused_total")
    else:
        _remember(key, cfg["cache_seconds"])
    return missing


async def join_required(session: AsyncSession, missing: list[dict[str, str]]) -> AppError:
    """The error the bot turns into its join screen: the admin's message + the channels still to join."""
    cfg = await load(session)
    return AppError("CHANNEL_JOIN_REQUIRED", cfg["message"], 403, {"channels": missing})


# ------------------------------------------------------------------------------------------------ admin probe
async def _probe_one(tg: TelegramChannel, bot_id: int, ch: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {"chat": ch["chat"], "title": ch["title"], "url": ch["url"], "ok": False, "problem": None}
    try:
        chat = await tg.get_chat(ch["chat"])
        out["telegram_title"] = chat.get("title")
        out["type"] = chat.get("type")
        member = await tg.get_chat_member(ch["chat"], bot_id)
    except TelegramApiError as exc:
        reason = (exc.description or "").lower()
        if "chat not found" in reason:
            out["problem"] = "کانال پیدا نشد؛ شناسه را بررسی کنید و ربات را به کانال اضافه کنید."
        elif exc.code == 403 or "kicked" in reason or "not a member" in reason:
            out["problem"] = "ربات عضو کانال نیست یا از آن حذف شده است."
        elif exc.permanent:
            out["problem"] = f"تلگرام درخواست را رد کرد: {exc.description[:150]}"
        else:
            out["problem"] = "تلگرام موقتاً در دسترس نیست؛ کمی بعد دوباره بررسی کنید."
        return out
    status = str(member.get("status") or "")
    out["bot_status"] = status
    if status not in ("administrator", "creator"):
        out["problem"] = "ربات باید ادمین کانال باشد؛ وگرنه تلگرام فهرست اعضا را به او نشان نمی‌دهد."
    elif out.get("type") not in ("channel", "supergroup"):
        out["problem"] = "این شناسه متعلق به کانال یا سوپرگروه نیست."
    else:
        out["ok"] = True
    return out


async def inspect(session: AsyncSession, cfg: dict[str, Any]) -> dict[str, Any]:
    """Read-only check of the given (not necessarily saved) channels: does each exist and is the main bot its admin?"""
    token = await main_bot_token(session)
    if not token:
        raise AppError("MAIN_BOT_TOKEN_MISSING", "توکن ربات اصلی تنظیم نشده است.", 409)
    tg = _channel(token)
    try:
        me = await tg.get_me()
    except TelegramApiError as exc:
        if exc.code in (401, 404):
            raise AppError("MAIN_BOT_TOKEN_INVALID", "توکن ربات اصلی معتبر نیست؛ آن را در تنظیمات ربات بررسی کنید.", 409) from exc
        raise AppError("TELEGRAM_UNREACHABLE", "اتصال به تلگرام برقرار نشد؛ کمی بعد دوباره امتحان کنید.", 502) from exc
    results = list(await asyncio.gather(*(_probe_one(tg, int(me["id"]), ch) for ch in cfg["channels"])))
    return {"bot_username": me.get("username"), "ok": all(r["ok"] for r in results), "channels": results}
