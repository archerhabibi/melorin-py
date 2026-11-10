"""Minimal async Telegram Bot API adapter for main and reseller channels.

The adapter is intentionally transport-only: identity, store isolation, authorization,
order state, pricing, and provisioning remain in Core.
"""

import asyncio
import weakref
from dataclasses import dataclass
from typing import Any
import httpx
from melorin.core.http import outbound_client

TELEGRAM_API = "https://api.telegram.org"
_POOL_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30.0)
# One keep-alive pool per running event loop (T03): httpx clients are bound to the loop that first used them, and the
# worker, the API and every test run their own loop. Entries vanish with their loop.
_pools: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()


def shared_client() -> httpx.AsyncClient:
    """The pooled client every Bot API call of the current event loop goes through. Never close it from a caller."""
    loop = asyncio.get_running_loop()
    client = _pools.get(loop)
    if client is None or client.is_closed:
        client = _pools[loop] = outbound_client("telegram_bot_api", limits=_POOL_LIMITS)
    return client


async def close_shared_clients() -> None:
    """Close the pool of the current loop (call from a shutdown hook)."""
    client = _pools.pop(asyncio.get_running_loop(), None)
    if client is not None and not client.is_closed:
        await client.aclose()


class TelegramApiError(RuntimeError):
    """A Telegram Bot API answer with ``ok=false`` (or a non-2xx status), with the parts callers need to decide a retry."""

    def __init__(self, code: int, description: str, retry_after: int | None = None):
        super().__init__(f"telegram {code}: {description}")
        self.code, self.description, self.retry_after = code, description, retry_after

    @property
    def permanent(self) -> bool:
        """400/401/403/404 mean the bot, group or topic is wrong; retrying cannot fix it. 429 and 5xx are transient."""
        return self.code in (400, 401, 403, 404)


async def get_me_response(
    token: str, *, timeout: float = 10.0, client: httpx.AsyncClient | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.Response:
    """Single raw ``getMe`` probe used by every token check (admin login settings, diagnostics, reseller onboarding).

    Returns the HTTP response so callers keep their own status handling (401/404 = rejected). Network errors propagate as
    ``httpx.HTTPError``; the bot token is never logged here (T03/T61).
    """
    url = f"{TELEGRAM_API}/bot{token}/getMe"
    if client is not None:
        return await client.get(url)
    if transport is not None:  # tests inject a transport; production uses the shared pool
        async with outbound_client("telegram_bot_api", timeout=timeout, transport=transport) as c:
            return await c.get(url)
    return await shared_client().get(url, timeout=timeout)


@dataclass(frozen=True)
class TelegramChannel:
    token: str
    core_base_url: str
    channel: str  # main | reseller
    timeout: float = 15.0

    def __post_init__(self):
        if self.channel not in {"main", "reseller"}:
            raise ValueError("channel must be main or reseller")
        if not self.token or not self.core_base_url:
            raise ValueError("Telegram token and Core URL are required")

    async def core(self, method: str, path: str, *, bot_secret: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"X-Bot-Secret": bot_secret, "Accept": "application/json"}
        async with outbound_client("telegram_core_api", base_url=self.core_base_url.rstrip("/"), timeout=self.timeout) as client:
            response = await client.request(method, path, headers=headers, json=json)
            response.raise_for_status()
            return response.json()

    async def telegram(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await shared_client().post(f"{TELEGRAM_API}/bot{self.token}/{method}", json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Telegram API request failed"))
        return data

    async def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """One Bot API call that raises :class:`TelegramApiError` (with ``retry_after``) instead of a bare RuntimeError."""
        try:
            response = await shared_client().post(f"{TELEGRAM_API}/bot{self.token}/{method}", json=payload, timeout=self.timeout)
        except httpx.HTTPError as exc:  # network / timeout: transient
            raise TelegramApiError(599, type(exc).__name__) from exc
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400 or not data.get("ok"):
            params = data.get("parameters") or {}
            raise TelegramApiError(
                int(data.get("error_code") or response.status_code),
                str(data.get("description") or "Telegram API request failed"),
                params.get("retry_after"),
            )
        return data

    async def send_to_topic(self, chat_id: int | str, text: str, *, thread_id: int | None = None) -> dict[str, Any]:
        """Plain-text message into a group, optionally into one forum topic. Raises :class:`TelegramApiError`."""
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if thread_id:
            payload["message_thread_id"] = int(thread_id)
        return await self.call("sendMessage", payload)

    async def get_me(self) -> dict[str, Any]:
        return (await self.call("getMe", {})).get("result") or {}

    async def get_chat(self, chat_id: int | str) -> dict[str, Any]:
        return (await self.call("getChat", {"chat_id": chat_id})).get("result") or {}

    async def get_chat_member(self, chat_id: int | str, user_id: int) -> dict[str, Any]:
        return (await self.call("getChatMember", {"chat_id": chat_id, "user_id": user_id})).get("result") or {}

    async def create_forum_topic(self, chat_id: int | str, name: str) -> int:
        """Create a forum topic and return its ``message_thread_id``."""
        result = (await self.call("createForumTopic", {"chat_id": chat_id, "name": name[:128]})).get("result") or {}
        return int(result["message_thread_id"])

    async def reopen_forum_topic(self, chat_id: int | str, thread_id: int) -> None:
        """Existence probe that never renames: Telegram answers ``TOPIC_NOT_MODIFIED`` for an open topic, succeeds (and
        reopens) a closed one and fails with "message thread not found" for a deleted one. Raises :class:`TelegramApiError`."""
        await self.call("reopenForumTopic", {"chat_id": chat_id, "message_thread_id": int(thread_id)})

    async def send_message(self, chat_id: int | str, text: str, **kwargs: Any) -> dict[str, Any]:
        return await self.telegram("sendMessage", {"chat_id": chat_id, "text": text, **kwargs})

    async def send_photo(
        self,
        chat_id: int | str,
        photo: bytes,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
        filename: str = "qr.png",
    ) -> dict[str, Any]:
        """Send one photo post (image + caption) in a single Telegram message."""
        import json as _json

        data: dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = _json.dumps(reply_markup)
        response = await shared_client().post(
            f"{TELEGRAM_API}/bot{self.token}/sendPhoto", data=data, files={"photo": (filename, photo, "image/png")}, timeout=self.timeout
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(result.get("description", "Telegram API request failed"))
        return result

    async def authenticate_update(self, update: dict[str, Any], *, bot_secret: str) -> dict[str, Any]:
        """Resolve Telegram identity through Core before any channel operation."""
        return await self.core("POST", "/api/v1/auth/telegram/bot", bot_secret=bot_secret, json={"update": update, "channel": self.channel})
