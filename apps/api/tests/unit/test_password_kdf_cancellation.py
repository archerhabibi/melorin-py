"""Cancelled requests must not free a KDF slot while its worker is still running."""

import asyncio
import itertools
import threading

import pytest

from melorin.core import security


@pytest.mark.parametrize("operation", ["hash", "verify"])
async def test_cancelled_kdf_keeps_its_slot_until_the_thread_finishes(monkeypatch, operation):
    monkeypatch.setattr(security, "_KDF_SLOTS", asyncio.Semaphore(2))
    started = [threading.Event() for _ in range(3)]
    finished = [threading.Event() for _ in range(3)]
    release = threading.Event()
    numbers = itertools.count()
    lock = threading.Lock()

    def slow_worker(*args):
        with lock:
            number = next(numbers)
        started[number].set()
        try:
            if not release.wait(10):
                raise TimeoutError("test did not release the worker")
            return "encoded" if operation == "hash" else True
        finally:
            finished[number].set()

    monkeypatch.setattr(security, "_hash_password_sync" if operation == "hash" else "_verify_password_sync", slow_worker)

    async def invoke():
        return await (security.hash_password("password") if operation == "hash" else security.verify_password("password", "encoded"))

    first = [asyncio.create_task(invoke()) for _ in range(2)]
    waiting = None
    try:
        for event in started[:2]:
            assert await asyncio.to_thread(event.wait, 5)
        for task in first:
            task.cancel()
        assert all(isinstance(result, asyncio.CancelledError) for result in await asyncio.gather(*first, return_exceptions=True))
        waiting = asyncio.create_task(invoke())
        assert not await asyncio.to_thread(started[2].wait, 0.5)
    finally:
        release.set()
        if waiting is not None:
            await asyncio.wait_for(waiting, timeout=5)
        for event in finished[:2]:
            assert await asyncio.to_thread(event.wait, 5)
    assert started[2].is_set()


@pytest.mark.parametrize("operation", ["hash", "verify"])
async def test_failed_kdf_releases_its_slot(monkeypatch, operation):
    monkeypatch.setattr(security, "_KDF_SLOTS", asyncio.Semaphore(1))
    calls = iter([False, True])

    def worker(*args):
        if not next(calls):
            raise ValueError("worker failed")
        return "encoded" if operation == "hash" else True

    monkeypatch.setattr(security, "_hash_password_sync" if operation == "hash" else "_verify_password_sync", worker)

    async def invoke():
        return await (security.hash_password("password") if operation == "hash" else security.verify_password("password", "encoded"))

    with pytest.raises(ValueError, match="worker failed"):
        await invoke()
    assert await asyncio.wait_for(invoke(), timeout=5)
