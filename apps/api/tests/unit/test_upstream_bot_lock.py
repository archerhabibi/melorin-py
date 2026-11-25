"""A chat lease must not be leaked, deleted for a new owner, or bypassed."""

import asyncio
import time

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
    with pytest.raises(PanelError) as exc:
        async with state._ChatLock("replacement", ttl=10, wait=2):
            pass
    assert exc.value.kind == ErrorKind.UNKNOWN
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


class ExpiringRedis:
    def __init__(self):
        self.value = None
        self.deadline = 0.0
        self.fail_renewal = False

    def _expire(self):
        if time.monotonic() >= self.deadline:
            self.value = None

    async def set(self, key, value, *, nx, ex):
        self._expire()
        if nx and self.value is not None:
            return False
        self.value, self.deadline = value, time.monotonic() + ex
        return True

    async def eval(self, script, count, key, token, *args):
        self._expire()
        if args and self.fail_renewal:
            raise ConnectionError("renewal unavailable")
        if self.value != token:
            return 0
        if args:
            self.deadline = time.monotonic() + int(args[0])
        else:
            self.value = None
        return 1


async def test_chat_lease_stays_owned_during_a_long_flow(monkeypatch):
    redis = ExpiringRedis()
    monkeypatch.setattr(state, "_redis", lambda: redis)
    lock = state._ChatLock("long-flow", ttl=1, wait=1)
    async with lock:
        await asyncio.sleep(1.2)  # longer than the original Redis TTL
        state._LOCKS.clear()  # another process has its own local mutex
        with pytest.raises(PanelError) as exc:
            async with state._ChatLock("long-flow", ttl=1, wait=0.1):
                pytest.fail("second chat entered while the first is active")
        assert exc.value.kind == ErrorKind.TRANSIENT
    assert redis.value is None


async def test_chat_lease_loss_stops_the_running_flow(monkeypatch):
    redis = ExpiringRedis()
    monkeypatch.setattr(state, "_redis", lambda: redis)
    entered = asyncio.Event()
    actions = []

    async def flow():
        async with state._ChatLock("lost-flow", ttl=1, wait=1):
            entered.set()
            await asyncio.sleep(4)
            actions.append("after lease loss")

    task = asyncio.create_task(flow())
    await asyncio.wait_for(entered.wait(), timeout=1)
    redis.value, redis.deadline = "replacement-owner", time.monotonic() + 10
    with pytest.raises(PanelError) as exc:
        await asyncio.wait_for(task, timeout=1.5)
    assert exc.value.kind == ErrorKind.UNKNOWN
    assert not actions and redis.value == "replacement-owner"


async def test_chat_lease_renewal_failure_stops_the_running_flow(monkeypatch):
    redis = ExpiringRedis()
    monkeypatch.setattr(state, "_redis", lambda: redis)
    entered = asyncio.Event()
    actions = []

    async def flow():
        async with state._ChatLock("failed-renewal", ttl=1, wait=1):
            entered.set()
            await asyncio.sleep(4)
            actions.append("after renewal failure")

    task = asyncio.create_task(flow())
    await asyncio.wait_for(entered.wait(), timeout=1)
    redis.fail_renewal = True
    with pytest.raises(PanelError) as exc:
        await asyncio.wait_for(task, timeout=1.5)
    assert exc.value.kind == ErrorKind.UNKNOWN
    assert not actions


async def test_chat_lease_lost_just_before_exit_is_an_unknown_outcome(monkeypatch):
    redis = ExpiringRedis()
    monkeypatch.setattr(state, "_redis", lambda: redis)
    with pytest.raises(PanelError) as exc:
        async with state._ChatLock("lost-on-exit", ttl=1, wait=1):
            redis.value, redis.deadline = "replacement-owner", time.monotonic() + 10
    assert exc.value.kind == ErrorKind.UNKNOWN
    assert redis.value == "replacement-owner"


async def test_chat_lease_release_error_is_an_unknown_outcome(monkeypatch):
    class ReleaseFailure(ExpiringRedis):
        async def eval(self, script, count, key, token, *args):
            if not args:
                raise ConnectionError("release unavailable")
            return await super().eval(script, count, key, token, *args)

    redis = ReleaseFailure()
    monkeypatch.setattr(state, "_redis", lambda: redis)
    with pytest.raises(PanelError) as exc:
        async with state._ChatLock("release-error", ttl=1, wait=1):
            pass
    assert exc.value.kind == ErrorKind.UNKNOWN


def test_chat_lease_requires_a_positive_whole_second():
    with pytest.raises(PanelError) as exc:
        state._ChatLock("bad-ttl", ttl=0, wait=1)
    assert exc.value.kind == ErrorKind.PERMANENT


async def test_external_cancellation_of_flow_still_releases_lease(monkeypatch):
    redis = ExpiringRedis()
    monkeypatch.setattr(state, "_redis", lambda: redis)
    entered = asyncio.Event()
    lock = state._ChatLock("external-cancel", ttl=1, wait=1)

    async def flow():
        async with lock:
            entered.set()
            await asyncio.sleep(4)

    task = asyncio.create_task(flow())
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert redis.value is None and not lock._local.locked()
