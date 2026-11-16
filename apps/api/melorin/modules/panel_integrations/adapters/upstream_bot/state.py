"""Shared state of the upstream-bot adapter: username -> upstream account mapping and the one-chat-one-flow lock.

Redis is used when available; a process-local copy keeps the adapter working (and testable) without it.
"""

import asyncio
import json
import logging
import time
import uuid

from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError

log = logging.getLogger("melorin.upstream_bot")

_MEM: dict[str, str] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def _redis():
    try:
        from melorin.core.redis import get_redis

        return get_redis()
    except Exception:  # pragma: no cover
        return None


class _Store:
    """username -> upstream account metadata. Redis when available, process memory otherwise."""

    def __init__(self, ns: str):
        self.ns = ns

    def _k(self, username: str) -> str:
        return f"upstream_bot:{self.ns}:acc:{username}"

    async def get(self, username: str) -> dict | None:
        r = _redis()
        raw = None
        if r is not None:
            try:
                raw = await r.get(self._k(username))
            except Exception:
                raw = None
        raw = raw or _MEM.get(self._k(username))
        return json.loads(raw) if raw else None

    async def set(self, username: str, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False)
        _MEM[self._k(username)] = raw
        r = _redis()
        if r is not None:
            try:
                await r.set(self._k(username), raw)
            except Exception:
                log.warning("upstream_bot: redis write failed for mapping", exc_info=True)

    async def delete(self, username: str) -> None:
        _MEM.pop(self._k(username), None)
        r = _redis()
        if r is not None:
            try:
                await r.delete(self._k(username))
            except Exception:
                log.warning("upstream_bot: redis delete failed", exc_info=True)

    async def name_taken(self, upstream_name: str) -> bool:
        """Is this upstream account name already mapped to a Melorin username?"""
        r = _redis()
        if r is None:
            return any(json.loads(v).get("ref") == upstream_name for k, v in _MEM.items() if k.startswith(f"upstream_bot:{self.ns}:acc:"))
        try:
            async for k in r.scan_iter(f"upstream_bot:{self.ns}:acc:*"):
                raw = await r.get(k)
                if raw and json.loads(raw).get("ref") == upstream_name:
                    return True
        except Exception:
            return False
        return False

    def seed(self, username: str, ref: str | None, subscription_url: str | None = None) -> None:
        """Re-seed the in-memory mapping (Redis may have been flushed). Never overwrites an existing entry."""
        key = self._k(username)
        if ref and key not in _MEM:
            _MEM[key] = json.dumps({"status": "active", "ref": ref, "subscription_url": subscription_url}, ensure_ascii=False)


class _ChatLock:
    def __init__(self, ns: str, ttl: int, wait: float):
        self.key, self.ttl, self.wait, self.token = f"upstream_bot:{ns}:lock", ttl, wait, uuid.uuid4().hex
        self._local = _LOCKS.setdefault(self.key, asyncio.Lock())
        self._held_redis = False

    async def __aenter__(self):
        await asyncio.wait_for(self._local.acquire(), self.wait)
        r, end = _redis(), time.monotonic() + self.wait
        if r is not None:
            while True:
                try:
                    if await r.set(self.key, self.token, nx=True, ex=self.ttl):
                        self._held_redis = True
                        break
                except Exception:
                    break  # redis down: the process-local lock still serialises this worker
                if time.monotonic() > end:
                    self._local.release()
                    raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: chat is busy, retry later")
                await asyncio.sleep(0.5)
        return self

    async def __aexit__(self, *exc):
        r = _redis()
        if r is not None and self._held_redis:
            try:
                if await r.get(self.key) == self.token:
                    await r.delete(self.key)
            except Exception:
                log.warning("upstream_bot: redis delete failed", exc_info=True)
        self._local.release()
