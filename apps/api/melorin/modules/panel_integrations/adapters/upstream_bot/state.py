"""Shared state of the upstream-bot adapter: username -> upstream account mapping and the one-chat-one-flow lock.

Redis errors stop shared-state operations. A process-local copy is available when Redis is explicitly absent.
"""

from __future__ import annotations

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

    def _check_lease(self, lease: _ChatLock) -> None:
        if lease.key != f"upstream_bot:{self.ns}:lock":
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: chat lock does not protect this purchase state")

    async def set(self, username: str, data: dict, *, lease: _ChatLock) -> None:
        self._check_lease(lease)
        raw = json.dumps(data, ensure_ascii=False)
        await lease._write_state(self._k(username), raw)
        _MEM[self._k(username)] = raw

    async def delete(self, username: str, *, lease: _ChatLock) -> None:
        self._check_lease(lease)
        await lease._write_state(self._k(username), None)
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
_RENEW_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_SET_STATE = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then
    return 0
end
redis.call('set', KEYS[2], ARGV[2])
return 1
"""
_DELETE_STATE = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then
    return 0
end
redis.call('del', KEYS[2])
return 1
"""


class _ChatLock:
    def __init__(self, ns: str, ttl: int, wait: float):
        self.key, self.ttl, self.wait, self.token = f"upstream_bot:{ns}:lock", ttl, wait, uuid.uuid4().hex
        if ttl < 1:
            raise PanelError(ErrorKind.PERMANENT, "upstream_bot: chat lock TTL must be at least one second")
        self._local = _LOCKS.setdefault(self.key, asyncio.Lock())
        self._redis_client = None
        self._owner: asyncio.Task[object] | None = None
        self._heartbeat: asyncio.Task[None] | None = None
        self._lease_lost = False
        self._held = False

    async def _write_state(self, key: str, raw: str | None) -> None:
        """Change state only while this lease owns the chat, atomically with the owner check."""
        if not self._held or self._lease_lost:
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: chat lock ownership lost")
        client = self._redis_client
        if client is None:  # The process-local lock protects the development-only memory store.
            return
        script = _DELETE_STATE if raw is None else _SET_STATE
        args = () if raw is None else (raw,)
        try:
            written = await asyncio.wait_for(client.eval(script, 2, self.key, key, self.token, *args), timeout=self.ttl / 3)
        except (RedisError, OSError, TimeoutError) as exc:
            self._lease_lost = True
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: shared purchase state unavailable") from exc
        if not written:
            self._lease_lost = True
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: chat lock ownership lost before state update")

    async def ensure_owned(self) -> None:
        if self._lease_lost:
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: chat lock ownership lost")
        client = self._redis_client
        if client is None:  # Redis is explicitly disabled in development.
            return
        try:
            renewed = await asyncio.wait_for(client.eval(_RENEW_LOCK, 1, self.key, self.token, self.ttl), timeout=self.ttl / 3)
        except (RedisError, OSError, TimeoutError) as exc:
            self._lease_lost = True
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: chat lock ownership could not be verified") from exc
        if not renewed:
            self._lease_lost = True
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: chat lock ownership lost")

    async def _renew_lease(self):
        try:
            while True:
                await asyncio.sleep(self.ttl / 3)
                await self.ensure_owned()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("upstream_bot: redis chat lease renewal failed", exc_info=True)
        self._lease_lost = True
        if self._owner is not None:
            self._owner.cancel()

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
                            self._owner = asyncio.current_task()
                            self._heartbeat = asyncio.create_task(self._renew_lease())
                            break
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: chat is busy, retry later")
                        await asyncio.sleep(min(0.5, remaining))
            except (RedisError, OSError) as exc:
                raise PanelError(ErrorKind.TRANSIENT, "upstream_bot: distributed chat lock unavailable") from exc
            self._held = True
            return self
        except BaseException:
            self._local.release()
            raise

    async def __aexit__(self, *exc):
        self._held = False
        try:
            if self._heartbeat is not None:
                self._heartbeat.cancel()
                await asyncio.gather(self._heartbeat, return_exceptions=True)
            if self._redis_client is not None:
                try:
                    if not await self._redis_client.eval(_RELEASE_LOCK, 1, self.key, self.token):
                        self._lease_lost = True
                except (RedisError, OSError):
                    self._lease_lost = True
                    log.warning("upstream_bot: redis lock release failed", exc_info=True)
        finally:
            self._local.release()
        if self._lease_lost:
            raise PanelError(ErrorKind.UNKNOWN, "upstream_bot: chat lock was lost; the operation outcome is unknown") from exc[1]
