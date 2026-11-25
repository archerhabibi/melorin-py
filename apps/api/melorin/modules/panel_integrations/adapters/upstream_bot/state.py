"""Shared state of the upstream-bot adapter: username -> upstream account mapping and the one-chat-one-flow lock.

Redis errors stop shared-state operations. A process-local copy is available when Redis is explicitly absent.
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


def _decode_mapping(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: stored purchase state is invalid") from exc
    if not isinstance(data, dict):
        raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: stored purchase state is invalid")
    return data


class _Store:
    """username -> upstream account metadata. Shared state must be readable and writable when configured."""

    def __init__(self, ns: str):
        self.ns = ns

    def _k(self, username: str) -> str:
        return f"upstream_bot:{self.ns}:acc:{username}"

    async def get(self, username: str) -> dict | None:
        try:
            r = _redis()
            raw = await r.get(self._k(username)) if r is not None else None
        except (RedisError, OSError) as exc:
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: shared purchase state unavailable") from exc
        if raw is None:
            raw = _MEM.get(self._k(username))
        return _decode_mapping(raw) if raw is not None else None

    async def set(self, username: str, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False)
        try:
            r = _redis()
            if r is not None and not await r.set(self._k(username), raw):
                raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: shared purchase state was not stored")
        except (RedisError, OSError) as exc:
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: shared purchase state unavailable") from exc
        _MEM[self._k(username)] = raw

    async def delete(self, username: str) -> None:
        try:
            r = _redis()
            if r is not None:
                await r.delete(self._k(username))
        except (RedisError, OSError) as exc:
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: shared purchase state unavailable") from exc
        _MEM.pop(self._k(username), None)

    async def name_taken(self, upstream_name: str) -> bool:
        """Is this upstream account name already mapped to a Melorin username?"""
        try:
            r = _redis()
            if r is None:
                return any(
                    _decode_mapping(v).get("ref") == upstream_name for k, v in _MEM.items() if k.startswith(f"upstream_bot:{self.ns}:acc:")
                )
            async for k in r.scan_iter(f"upstream_bot:{self.ns}:acc:*"):
                raw = await r.get(k)
                if raw is not None and _decode_mapping(raw).get("ref") == upstream_name:
                    return True
        except (RedisError, OSError) as exc:
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: shared purchase state unavailable") from exc
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
