"""Telethon implementation of ChatClient. Telethon is imported lazily so the API image works without it."""

import asyncio

from melorin.modules.vpn.adapters.base import ErrorKind, PanelError
from melorin.modules.vpn.adapters.upstream_bot.chat import Button, Msg


def _to_msg(m) -> Msg:
    buttons: list[Button] = []
    for r, row in enumerate(getattr(m, "buttons", None) or []):
        for c, b in enumerate(row):
            buttons.append(Button(getattr(b, "text", "") or "", getattr(getattr(b, "button", None), "data", None), r, c))
    return Msg(m.id, m.message or "", buttons, bool(getattr(m, "media", None)), m.date.timestamp() if m.date else 0.0)


class TelethonChat:
    def __init__(self, api_id: int, api_hash: str, session: str, bot_username: str, timeout: float = 25):
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
        except ImportError as exc:  # pragma: no cover
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: telethon is not installed") from exc
        self.entity_name = bot_username.lstrip("@")
        self.timeout = timeout
        self._c = TelegramClient(StringSession(session), api_id, api_hash, sequential_updates=True)
        self._entity = None

    async def _ready(self):
        if not self._c.is_connected():
            try:
                await asyncio.wait_for(self._c.connect(), self.timeout)
            except (TimeoutError, OSError) as exc:
                raise PanelError(ErrorKind.TRANSIENT, f"upstream_bot: telegram connect failed: {exc}") from exc
        if not await self._c.is_user_authorized():
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: userbot session is not authorized (re-login required)")
        if self._entity is None:
            self._entity = await self._c.get_entity(self.entity_name)

    async def _call(self, coro):
        try:
            return await asyncio.wait_for(coro, self.timeout)
        except TimeoutError as exc:
            raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: telegram timeout") from exc
        except PanelError:
            raise
        except Exception as exc:  # FloodWait, RPC errors, network
            kind = ErrorKind.TRANSIENT if type(exc).__name__ in {"FloodWaitError", "ConnectionError", "TimeoutError"} else ErrorKind.UNKNOWN
            raise PanelError(kind, f"upstream_bot: telegram error {type(exc).__name__}: {exc}") from exc

    async def send_text(self, text: str) -> int:
        await self._ready()
        m = await self._call(self._c.send_message(self._entity, text))
        return m.id

    async def click(self, msg: Msg, button: Button) -> None:
        await self._ready()
        if button.data is None:  # reply keyboard: it is just a text message
            await self.send_text(button.text)
            return
        m = await self._call(self._c.get_messages(self._entity, ids=msg.id))
        await self._call(m.click(button.row, button.col))

    async def recent(self, limit: int = 15) -> list[Msg]:
        await self._ready()
        return [_to_msg(m) for m in await self._call(self._c.get_messages(self._entity, limit=limit))]

    async def get(self, msg_id: int) -> Msg | None:
        await self._ready()
        m = await self._call(self._c.get_messages(self._entity, ids=msg_id))
        return _to_msg(m) if m else None

    async def close(self) -> None:
        if self._c.is_connected():
            await self._c.disconnect()
