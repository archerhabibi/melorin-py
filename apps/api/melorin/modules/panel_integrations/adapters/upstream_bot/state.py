"""Shared state of the upstream-bot adapter: username -> upstream account mapping and the one-chat-one-flow lock.

Redis is used when available; a process-local copy keeps the adapter working (and testable) without it.
"""

import asyncio
import json
import logging
import time
import uuid

from redis.exceptions import RedisError

from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError

log = logging.getLogger("melorin.upstream_bot")

_MEM: dict[str, str] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def _redis():
    from melorin.core.redis import get_redis

    return get_redis()


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


# Redis must compare the owner and delete as one operation: a lease may expire between separate GET and DEL calls.
_RELEASE_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class _ChatLock:
    def __init__(self, ns: str, ttl: int, wait: float):
        self.key, self.ttl, self.wait, self.token = f"upstream_bot:{ns}:lock", ttl, wait, uuid.uuid4().hex
        self._local = _LOCKS.setdefault(self.key, asyncio.Lock())
        self._redis_client = None

    async def __aenter__(self):
        deadline = time.monotonic() + self.wait
        try:
            await asyncio.wait_for(self._local.acquire(), self.wait)
        except TimeoutError as exc:
            raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: chat is busy, retry later") from exc
        try:
            try:
                r = _redis()
                if r is not None:
                    while True:
                        if await r.set(self.key, self.token, nx=True, ex=self.ttl):
                            self._redis_client = r
                            break
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: chat is busy, retry later")
                        await asyncio.sleep(min(0.5, remaining))
            except (RedisError, OSError) as exc:
                raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: distributed chat lock unavailable") from exc
            return self
        except BaseException:
            self._local.release()
            raise

    async def __aexit__(self, *exc):
        try:
            if self._redis_client is not None:
                try:
                    await self._redis_client.eval(_RELEASE_LOCK, 1, self.key, self.token)
                except (RedisError, OSError):
                    log.warning("upstream_bot: redis lock release failed", exc_info=True)
        finally:
            self._local.release()
