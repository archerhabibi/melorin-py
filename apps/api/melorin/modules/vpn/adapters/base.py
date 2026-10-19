"""Standard Panel Adapter interface (doc 03). Every panel gets its own adapter + contract tests."""

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

GB = 1024**3


class ErrorKind(StrEnum):
    TRANSIENT = "transient"  # timeouts, 5xx: retry with backoff
    PERMANENT = "permanent"  # 4xx validation: manual review
    UNKNOWN = "unknown"  # outcome unclear: check panel state before retrying


class PanelError(Exception):
    def __init__(self, kind: ErrorKind, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


@dataclass
class AccountSpec:
    username: str
    expire_at: dt.datetime | None
    traffic_bytes: int  # 0 = unlimited
    max_devices: int | None = None
    note: str | None = None


@dataclass
class PanelAccount:
    ref: str
    username: str
    status: str  # normalized: active | disabled | expired | limited | unknown
    expire_at: dt.datetime | None
    traffic_limit_bytes: int
    traffic_used_bytes: int
    subscription_url: str | None = None
    links: list[str] = field(default_factory=list)


@dataclass
class Capabilities:
    suspend: bool = True
    extend: bool = True
    subscription_url: bool = True
    traffic_reset: bool = False


class PanelAdapter(Protocol):
    kind: str

    async def health_check(self) -> bool: ...
    def capabilities(self) -> Capabilities: ...
    async def create_account(self, spec: AccountSpec) -> PanelAccount: ...
    async def get_account(self, username: str) -> PanelAccount | None: ...
    async def suspend_account(self, username: str) -> None: ...
    async def resume_account(self, username: str) -> None: ...
    async def extend_account(self, username: str, *, expire_at: dt.datetime | None, traffic_bytes: int) -> PanelAccount: ...
    async def revoke_account(self, username: str) -> None: ...
    # Optional (``Capabilities.traffic_reset``): zero the usage counter. Renewal falls back to a higher limit without it.
    # async def reset_traffic(self, username: str) -> PanelAccount: ...
    async def close(self) -> None: ...
    def normalize_status(self, raw: str) -> str: ...


def classify_http(status: int) -> ErrorKind:
    if status >= 500 or status in (408, 429):
        return ErrorKind.TRANSIENT
    return ErrorKind.PERMANENT
