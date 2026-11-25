"""A chat lease must not be leaked, deleted for a new owner, or bypassed."""

import asyncio

import pytest

from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError
from melorin.modules.panel_integrations.adapters.upstream_bot import state


async def test_cancelled_redis_acquisition_releases_local_lock(monkeypatch):
    started = asyncio.Event()

    class WaitingRedis:
        async def set(self, *args, **kwargs):
            started.set()
            await asyncio.Future()

    monkeypatch.setattr(state, "_redis", lambda: WaitingRedis())
    lock = state._ChatLock("cancel-acquire", ttl=10, wait=2)
    task = asyncio.create_task(lock.__aenter__())
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not lock._local.locked()


async def test_cancelled_redis_release_still_releases_local_lock(monkeypatch):
    started = asyncio.Event()

    class WaitingRedis:
        async def set(self, *args, **kwargs):
            return True

        async def get(self, *args):
            started.set()
            await asyncio.Future()

        async def eval(self, *args):
            started.set()
            await asyncio.Future()

    redis = WaitingRedis()
    monkeypatch.setattr(state, "_redis", lambda: redis)
    lock = state._ChatLock("cancel-release", ttl=10, wait=2)
    await lock.__aenter__()
    task = asyncio.create_task(lock.__aexit__(None, None, None))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not lock._local.locked()


async def test_redis_failure_cannot_bypass_distributed_lock(monkeypatch):
    class OfflineRedis:
        async def set(self, *args, **kwargs):
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr(state, "_redis", lambda: OfflineRedis())
    lock = state._ChatLock("offline", ttl=10, wait=2)
    with pytest.raises(PanelError) as exc:
        async with lock:
            pytest.fail("chat entered without distributed lock")
    assert exc.value.kind == ErrorKind.TRANSIENT
    assert not lock._local.locked()


async def test_local_lock_timeout_is_a_retryable_panel_error(monkeypatch):
    monkeypatch.setattr(state, "_redis", lambda: None)
    lock = state._ChatLock("busy-local", ttl=10, wait=0.01)
    await lock._local.acquire()
    try:
        with pytest.raises(PanelError) as exc:
            async with lock:
                pytest.fail("busy chat entered")
        assert exc.value.kind == ErrorKind.TRANSIENT
    finally:
        lock._local.release()


async def test_release_never_deletes_a_replacement_owners_lock(monkeypatch):
    class ReplacingRedis:
        value = None

        async def set(self, key, value, **kwargs):
            self.value = value
            return True

        async def get(self, key):
            prior = self.value
            self.value = "replacement-owner"  # lease expired between GET and DEL
            return prior

        async def delete(self, key):
            self.value = None

        async def eval(self, script, number_of_keys, key, token):
            self.value = "replacement-owner"  # new owner is present before the atomic comparison
            if self.value == token:
                self.value = None
                return 1
            return 0

    redis = ReplacingRedis()
    monkeypatch.setattr(state, "_redis", lambda: redis)
    async with state._ChatLock("replacement", ttl=10, wait=2):
        pass
    assert redis.value == "replacement-owner"


async def test_redis_client_creation_failure_cannot_fall_back_to_local_lock(monkeypatch):
    from melorin.core import redis as redis_module

    def unavailable():
        raise ConnectionError("redis configuration unavailable")

    monkeypatch.setattr(redis_module, "get_redis", unavailable)
    lock = state._ChatLock("factory-failure", ttl=10, wait=2)
    with pytest.raises(PanelError) as exc:
        async with lock:
            pytest.fail("chat entered without distributed lock")
    assert exc.value.kind == ErrorKind.TRANSIENT
    assert not lock._local.locked()
