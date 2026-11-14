"""Chat transport abstraction: the adapter talks to this protocol, never to Telethon directly (tests use a fake)."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Button:
    text: str
    data: bytes | None = None  # inline callback data; None for reply-keyboard buttons
    row: int = 0
    col: int = 0


@dataclass
class Msg:
    id: int
    text: str
    buttons: list[Button] = field(default_factory=list)
    has_media: bool = False
    date_ts: float = 0.0


class ChatClient(Protocol):
    async def send_text(self, text: str) -> int: ...
    async def click(self, msg: Msg, button: Button) -> None: ...
    async def recent(self, limit: int = 15) -> list[Msg]:
        """Newest first."""

    async def get(self, msg_id: int) -> Msg | None: ...
    async def close(self) -> None: ...
