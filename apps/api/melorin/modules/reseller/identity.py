"""Validation of the two identifiers a reseller application brings: the store hostname and the Telegram bot.

Pure helpers (no database) so Core, tests and any channel use exactly one set of rules.
"""

import ipaddress
import re
from urllib.parse import urlparse

import httpx

from melorin.core.config import get_settings
from melorin.core.errors import AppError

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD = re.compile(r"^(?:[a-z]{2,24}|xn--[a-z0-9-]{2,59})$")
_TOKEN = re.compile(r"^(?P<bot_id>\d{6,15}):(?P<secret>[A-Za-z0-9_-]{30,64})$")
_RESERVED_SUFFIXES = (".local", ".localhost", ".internal", ".invalid", ".test", ".example", ".lan")


def platform_hosts() -> set[str]:
    """Hostnames that belong to the platform itself and can never be handed to a reseller."""
    s = get_settings()
    hosts = set()
    for url in [s.store_web_url, s.public_api_url, *s.cors_origins]:
        if url and (host := urlparse(url).hostname):
            hosts.add(host.lower())
    return hosts


def normalize_domain(raw: str) -> str:
    """'  https://Shop.Example.com/path?x=1 ' -> 'shop.example.com'. Raises AppError(INVALID_DOMAIN)."""
    value = (raw or "").strip().lower()
    if "://" in value:
        value = urlparse(value).netloc or ""
    value = value.split("/")[0].split("?")[0].split("#")[0].rstrip(".")
    if "@" in value or ":" in value:
        raise AppError("INVALID_DOMAIN", "دامنه نباید شامل پورت، نام کاربری یا آدرس IP باشد.", 422)
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise AppError("INVALID_DOMAIN", "به‌جای آدرس IP باید نام دامنه وارد شود.", 422)
    labels = value.split(".")
    if len(value) > 253 or len(labels) < 2 or not all(_LABEL.match(x) for x in labels) or not _TLD.match(labels[-1]):
        raise AppError("INVALID_DOMAIN", "نام دامنه معتبر نیست (نمونه: shop.example.com).", 422)
    if value.endswith(_RESERVED_SUFFIXES) or value == "localhost":
        raise AppError("INVALID_DOMAIN", "این دامنه قابل استفاده نیست.", 422)
    if value in platform_hosts():
        raise AppError("DOMAIN_RESERVED", "این دامنه متعلق به پلتفرم است.", 409)
    return value


def parse_bot_token(raw: str) -> tuple[str, str]:
    """Return (token, bot_key). bot_key is the stable 'tg:<bot id>' identity and never contains the secret."""
    token = (raw or "").strip()
    m = _TOKEN.match(token)
    if not m:
        raise AppError("INVALID_BOT_TOKEN", "فرمت توکن ربات معتبر نیست (نمونه: 123456789:AA…).", 422)
    return token, f"tg:{m.group('bot_id')}"


async def verify_bot(token: str, *, transport: httpx.AsyncBaseTransport | None = None) -> str | None:
    """Ask Telegram who owns the token. Returns the bot username when verified, None when Telegram is unreachable.

    A definite rejection by Telegram raises BOT_TOKEN_REJECTED; a network failure does not block the
    application (the admin sees the bot as 'unverified' and can re-check it from the review screen before approving).
    """
    try:
        async with httpx.AsyncClient(timeout=8, transport=transport) as client:
            r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
    except httpx.HTTPError:
        return None
    if r.status_code in (401, 404):
        raise AppError("BOT_TOKEN_REJECTED", "تلگرام این توکن را نپذیرفت؛ توکن را از BotFather دوباره بگیرید.", 422)
    if r.status_code != 200:
        return None
    result = (r.json() or {}).get("result") or {}
    if not result.get("is_bot", True) or not result.get("username"):
        raise AppError("BOT_TOKEN_REJECTED", "این توکن متعلق به یک ربات نیست.", 422)
    return str(result["username"])


async def ensure_identity_free(session, *, domain: str, bot_key: str, bot_username: str | None = None, exclude_application_id=None) -> None:
    """Domain and bot must be unique across stores, bot bindings and other pending applications."""
    from sqlalchemy import func, select

    from melorin.kernel.models.stores import BotStoreBinding, ResellerApplication, Store

    def other_pending(col, value):
        q = select(ResellerApplication.id).where(col == value, ResellerApplication.status == "pending")
        return q.where(ResellerApplication.id != exclude_application_id) if exclude_application_id else q

    if await session.scalar(select(Store.id).where(Store.domain == domain)) or await session.scalar(
        other_pending(ResellerApplication.domain, domain)
    ):
        raise AppError("DOMAIN_TAKEN", "این دامنه قبلاً برای فروشگاه یا درخواست دیگری ثبت شده است.", 409)
    taken = await session.scalar(select(BotStoreBinding.id).where(BotStoreBinding.bot_key == bot_key)) or await session.scalar(
        other_pending(ResellerApplication.bot_key, bot_key)
    )
    if not taken and bot_username:
        uname = bot_username.lower()
        taken = await session.scalar(
            select(BotStoreBinding.id).where(func.lower(BotStoreBinding.bot_username) == uname)
        ) or await session.scalar(select(Store.id).where(func.lower(Store.bot_username) == uname))
    if taken:
        raise AppError("BOT_TAKEN", "این ربات قبلاً برای فروشگاه یا درخواست دیگری ثبت شده است.", 409)
