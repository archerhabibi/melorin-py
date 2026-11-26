"""Mandatory channel membership ("force join") for the main Telegram bot.

Pure logic, no I/O: validation of the admin-edited configuration, the membership rule applied to a Telegram
``ChatMember`` and the small projection a refused bot user is shown. Telegram calls live in
``melorin.modules.channel_gate``; the admin editor in ``melorin.modules.admin.channel_join``.

A channel is named by its public ``@username`` or, for a private channel, by its numeric id (``-100...``). A private
channel has no public link, so the admin must give its invite link (``https://t.me/+...``); a public one gets
``https://t.me/<username>`` automatically. The bot must be an administrator of every channel, otherwise Telegram does
not tell it who the members are (``getChatMember`` answers "member list is inaccessible").
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MAX_CHANNELS = 5
MAX_TITLE = 64
MAX_MESSAGE = 1000
MIN_CACHE_SECONDS = 0
MAX_CACHE_SECONDS = 3600

DEFAULT_MESSAGE = "برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شوید و سپس روی «✅ عضو شدم» بزنید."

DEFAULT: dict[str, Any] = {"enabled": False, "channels": [], "message": DEFAULT_MESSAGE, "cache_seconds": 300}

# Telegram usernames: 5-32 chars, letters/digits/underscore, starting with a letter (https://core.telegram.org/method/account.checkUsername).
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,30}[A-Za-z0-9]\Z")
CHAT_ID_RE = re.compile(r"^-100[0-9]{5,16}\Z")  # supergroup / channel ids
LINK_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?P<path>[^?#\s]+)/?(?:[?#].*)?\Z", re.IGNORECASE)
INVITE_RE = re.compile(r"^https://(?:t|telegram)\.me/(?:\+|joinchat/)[A-Za-z0-9_-]{8,64}\Z", re.IGNORECASE)
PUBLIC_URL_RE = re.compile(r"^https://(?:t|telegram)\.me/[A-Za-z][A-Za-z0-9_]{3,30}[A-Za-z0-9]\Z", re.IGNORECASE)

# Telegram ChatMember statuses (https://core.telegram.org/bots/api#chatmember).
MEMBER_STATUSES = frozenset({"creator", "administrator", "member"})

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class ChannelJoinError(ValueError):
    """The submitted configuration is invalid; the message is Persian and shown to the admin as is."""


def _str(value: Any, field: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool) and field == "شناسهٔ کانال":
        return str(value)
    raise ChannelJoinError(f"«{field}» باید متن باشد.")


def parse_chat(raw: Any) -> str:
    """``@name`` / ``name`` / ``t.me/name`` / ``https://t.me/name`` -> ``@name``; ``-100...`` stays numeric (as text).

    An invite link (``t.me/+...``) cannot identify the channel: the bot needs the numeric id for that.
    """
    text = _str(raw, "شناسهٔ کانال").translate(_DIGITS)
    if not text:
        raise ChannelJoinError("شناسهٔ کانال خالی است.")
    if CHAT_ID_RE.match(text):
        return text
    m = LINK_RE.match(text)
    if m:
        path = m.group("path")
        if path.startswith("+") or path.lower().startswith("joinchat/"):
            raise ChannelJoinError(
                "لینک دعوت کانال خصوصی شناسهٔ کانال نیست؛ شناسهٔ عددی کانال (مثل ‎-1001234567890‎) را وارد کنید و لینک دعوت را در فیلد «لینک عضویت» بگذارید."
            )
        text = path.split("/")[0]
    name = text.removeprefix("@")
    if not USERNAME_RE.match(name):
        raise ChannelJoinError(f"«{text}» شناسهٔ معتبر کانال نیست؛ ‎@username‎ کانال عمومی یا شناسهٔ عددی ‎-100…‎ کانال خصوصی را وارد کنید.")
    return "@" + name


def _url(raw: Any, chat: str) -> str:
    url = _str(raw, "لینک عضویت")
    if not url:
        if chat.startswith("@"):
            return f"https://t.me/{chat[1:]}"
        raise ChannelJoinError(f"کانال خصوصی {chat}: لینک دعوت (مثل ‎https://t.me/+AbCd…‎) لازم است.")
    if url.lower().startswith("http://"):
        url = "https://" + url[7:]
    elif not url.lower().startswith("https://"):
        url = "https://" + url
    if not (INVITE_RE.match(url) or PUBLIC_URL_RE.match(url)):
        raise ChannelJoinError(f"کانال {chat}: لینک عضویت باید یک لینک ‎t.me‎ باشد (‎https://t.me/name‎ یا ‎https://t.me/+…‎).")
    return url


def normalize_channel(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ChannelJoinError("هر کانال باید یک شیء با «chat» باشد.")
    chat = parse_chat(raw.get("chat"))
    title = _str(raw.get("title"), "عنوان")[:MAX_TITLE] or chat
    return {"chat": chat, "title": title, "url": _url(raw.get("url"), chat)}


def normalize(raw: Any) -> dict[str, Any]:
    """Validate and canonicalise the admin's submission. Raises :class:`ChannelJoinError` with a Persian message."""
    if not isinstance(raw, dict):
        raise ChannelJoinError("پیکربندی نامعتبر است.")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ChannelJoinError("«فعال» باید درست/نادرست باشد.")
    channels_raw = raw.get("channels") or []
    if not isinstance(channels_raw, list):
        raise ChannelJoinError("فهرست کانال‌ها نامعتبر است.")
    if len(channels_raw) > MAX_CHANNELS:
        raise ChannelJoinError(f"حداکثر {MAX_CHANNELS} کانال مجاز است.")
    channels: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in channels_raw:
        ch = normalize_channel(item)
        key = ch["chat"].lower()
        if key in seen:
            raise ChannelJoinError(f"کانال {ch['chat']} دو بار آمده است.")
        seen.add(key)
        channels.append(ch)
    if enabled and not channels:
        raise ChannelJoinError("برای فعال کردن عضویت اجباری دست‌کم یک کانال اضافه کنید.")
    message = _str(raw.get("message"), "متن پیام") or DEFAULT_MESSAGE
    if len(message) > MAX_MESSAGE:
        raise ChannelJoinError(f"متن پیام حداکثر {MAX_MESSAGE} نویسه است.")
    cache = raw.get("cache_seconds", DEFAULT["cache_seconds"])
    if isinstance(cache, bool) or not isinstance(cache, int) or not MIN_CACHE_SECONDS <= cache <= MAX_CACHE_SECONDS:
        raise ChannelJoinError(f"مدت به‌خاطرسپاری عضویت باید عددی بین {MIN_CACHE_SECONDS} و {MAX_CACHE_SECONDS} ثانیه باشد.")
    return {"enabled": enabled, "channels": channels, "message": message, "cache_seconds": cache}


def stored(raw: Any) -> dict[str, Any]:
    """The saved row, re-validated; an unreadable row (hand edit, old shape) reads as the safe default: OFF."""
    if raw is None:
        return {**DEFAULT, "channels": []}
    try:
        return normalize(raw)
    except ChannelJoinError:
        return {**DEFAULT, "channels": []}


def is_member(member: dict[str, Any]) -> bool:
    """A Telegram ``ChatMember`` counts as joined when it is the owner, an admin, a member, or a restricted member who is
    still in the chat. ``left`` and ``kicked`` (banned) do not."""
    status = str(member.get("status") or "")
    if status in MEMBER_STATUSES:
        return True
    return status == "restricted" and bool(member.get("is_member"))


def fingerprint(cfg: dict[str, Any]) -> str:
    """Changes whenever the set of channels changes, so a cached "is a member" never outlives the channels it was checked on."""
    chats = sorted(ch["chat"].lower() for ch in cfg.get("channels") or [])
    return hashlib.sha256(json.dumps(chats).encode()).hexdigest()[:16]


def public_channel(ch: dict[str, str]) -> dict[str, str]:
    """What a refused user is shown for one channel: its title and the link to join. Never the numeric id."""
    return {"title": ch["title"], "url": ch["url"]}
