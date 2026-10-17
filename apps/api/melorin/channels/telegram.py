"""Minimal async Telegram Bot API adapter for main and reseller channels.

The adapter is intentionally transport-only: identity, store isolation, authorization,
order state, pricing, and provisioning remain in Core.
"""

from dataclasses import dataclass
from typing import Any
import httpx


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
        async with httpx.AsyncClient(base_url=self.core_base_url.rstrip("/"), timeout=self.timeout) as client:
            response = await client.request(method, path, headers=headers, json=json)
            response.raise_for_status()
            return response.json()

    async def telegram(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=f"https://api.telegram.org/bot{self.token}", timeout=self.timeout) as client:
            response = await client.post(f"/{method}", json=payload)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("description", "Telegram API request failed"))
            return data

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
        async with httpx.AsyncClient(base_url=f"https://api.telegram.org/bot{self.token}", timeout=self.timeout) as client:
            response = await client.post("/sendPhoto", data=data, files={"photo": (filename, photo, "image/png")})
            response.raise_for_status()
            result = response.json()
            if not result.get("ok"):
                raise RuntimeError(result.get("description", "Telegram API request failed"))
            return result

    async def authenticate_update(self, update: dict[str, Any], *, bot_secret: str) -> dict[str, Any]:
        """Resolve Telegram identity through Core before any channel operation."""
        return await self.core("POST", "/api/v1/auth/telegram/bot", bot_secret=bot_secret, json={"update": update, "channel": self.channel})
