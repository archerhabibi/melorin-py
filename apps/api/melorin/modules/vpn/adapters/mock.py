"""Deterministic in-memory panel for development, demos and tests."""

import datetime as dt
import random

from melorin.modules.vpn.adapters.base import AccountSpec, Capabilities, ErrorKind, PanelAccount, PanelError

_STATE: dict[str, PanelAccount] = {}


class MockPanelAdapter:
    kind = "mock"

    def __init__(self, base_url: str = "http://mock.panel", config: dict | None = None, **_):
        self.base_url = base_url.rstrip("/")
        self.fail_rate = float((config or {}).get("fail_rate", 0))

    def _maybe_fail(self):
        if self.fail_rate and random.random() < self.fail_rate:
            raise PanelError(ErrorKind.TRANSIENT, "mock transient failure")

    async def health_check(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities()

    async def create_account(self, spec: AccountSpec) -> PanelAccount:
        self._maybe_fail()
        acc = PanelAccount(
            ref=spec.username,
            username=spec.username,
            status="active",
            expire_at=spec.expire_at,
            traffic_limit_bytes=spec.traffic_bytes,
            traffic_used_bytes=0,
            subscription_url=f"{self.base_url}/sub/{spec.username}",
            links=[f"vless://{spec.username}@mock.panel:443?security=reality#Melorin"],
        )
        _STATE[spec.username] = acc
        return acc

    async def get_account(self, username: str) -> PanelAccount | None:
        return _STATE.get(username)

    async def suspend_account(self, username: str) -> None:
        if username in _STATE:
            _STATE[username].status = "disabled"

    async def resume_account(self, username: str) -> None:
        if username in _STATE:
            _STATE[username].status = "active"

    async def extend_account(self, username: str, *, expire_at: dt.datetime | None, traffic_bytes: int) -> PanelAccount:
        acc = _STATE.get(username) or await self.create_account(AccountSpec(username, expire_at, traffic_bytes))
        acc.expire_at, acc.traffic_limit_bytes, acc.status = expire_at, traffic_bytes, "active"
        return acc

    async def reset_traffic(self, username: str) -> PanelAccount:
        acc = _STATE[username]
        acc.traffic_used_bytes = 0
        return acc

    async def revoke_account(self, username: str) -> None:
        _STATE.pop(username, None)

    def normalize_status(self, raw: str) -> str:
        return raw

    async def close(self) -> None:
        return None
