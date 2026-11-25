"""Audit T27: poll_tick never runs more than TICK_CONCURRENCY outbox/webhook rows at the same time."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from melorin.worker import arq_app


class _Redis:
    def __init__(self):
        self.calls = []

    async def set(self, *a, **k):
        self.calls.append((a, k))
        return True


@pytest.mark.asyncio
async def test_poll_tick_bounds_concurrency(monkeypatch):
    running = peak = 0

    async def work(_row):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    async def events(_s):
        return list(range(20))

    async def hooks(_s):
        return list(range(20))

    @asynccontextmanager
    async def _session():
        yield object()

    monkeypatch.setattr(arq_app, "session_factory", lambda: _session)
    monkeypatch.setattr(arq_app, "claim_batch", events)
    monkeypatch.setattr(arq_app, "claim_webhook_batch", hooks)
    monkeypatch.setattr(arq_app, "process_event", work)
    monkeypatch.setattr(arq_app, "process_webhook", work)

    out = await arq_app.poll_tick({"redis": _Redis(), "poll_tick_lock": asyncio.Lock()})
    assert out == {"events": 20, "deliveries": 20}
    assert 1 < peak <= arq_app.TICK_CONCURRENCY


@pytest.mark.asyncio
async def test_overlapping_ticks_skip_claims_but_still_refresh_heartbeat(monkeypatch):
    active = peak = claims = 0
    full, overflow, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def work(_row):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == arq_app.TICK_CONCURRENCY:
            full.set()
        if active > arq_app.TICK_CONCURRENCY:
            overflow.set()
        try:
            await release.wait()
        finally:
            active -= 1

    async def events(_s):
        nonlocal claims
        claims += 1
        return list(range(20))

    async def hooks(_s):
        return []

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(arq_app, "session_factory", lambda: session)
    monkeypatch.setattr(arq_app, "claim_batch", events)
    monkeypatch.setattr(arq_app, "claim_webhook_batch", hooks)
    monkeypatch.setattr(arq_app, "process_event", work)
    redis = _Redis()
    ctx = {"redis": redis, "poll_tick_lock": asyncio.Lock()}
    first = asyncio.create_task(arq_app.poll_tick(ctx))
    second = overflow_waiter = None
    try:
        await asyncio.wait_for(full.wait(), timeout=2)
        # ARQ copies the startup context for each job, while sharing its objects.
        second = asyncio.create_task(arq_app.poll_tick(dict(ctx)))
        overflow_waiter = asyncio.create_task(overflow.wait())
        done, _ = await asyncio.wait({second, overflow_waiter}, timeout=2, return_when=asyncio.FIRST_COMPLETED)
        assert second in done, f"overlapping ticks reached {peak} concurrent rows"
        assert await second == {"events": 0, "deliveries": 0, "skipped": True}
        assert not overflow.is_set()
        assert claims == 1
        assert len(redis.calls) == 1  # a long batch must not make the worker look dead
        release.set()
        assert await first == {"events": 20, "deliveries": 0}
        assert await arq_app.poll_tick(dict(ctx)) == {"events": 20, "deliveries": 0}
        assert claims == 2
    finally:
        release.set()
        if overflow_waiter is not None:
            overflow_waiter.cancel()
        await asyncio.gather(*(task for task in (first, second, overflow_waiter) if task is not None), return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_row_does_not_leave_other_rows_running_after_tick_exits(monkeypatch):
    started, failed, release, finished = (asyncio.Event() for _ in range(4))

    async def work(row):
        if row == "slow":
            started.set()
            await release.wait()
            finished.set()
        else:
            await started.wait()
            failed.set()
            raise RuntimeError("row failed")

    async def events(_s):
        return ["slow", "bad"]

    async def hooks(_s):
        return []

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(arq_app, "session_factory", lambda: session)
    monkeypatch.setattr(arq_app, "claim_batch", events)
    monkeypatch.setattr(arq_app, "claim_webhook_batch", hooks)
    monkeypatch.setattr(arq_app, "process_event", work)
    ctx = {"redis": _Redis(), "poll_tick_lock": asyncio.Lock()}
    tick = asyncio.create_task(arq_app.poll_tick(ctx))
    try:
        await asyncio.wait_for(failed.wait(), timeout=2)
        done, _ = await asyncio.wait({tick}, timeout=0.1)
        assert not done, "the tick returned while another row was still running"
        assert await arq_app.poll_tick(dict(ctx)) == {"events": 0, "deliveries": 0, "skipped": True}
        release.set()
        with pytest.raises(RuntimeError, match="row failed"):
            await tick
        assert finished.is_set()
        assert not ctx["poll_tick_lock"].locked()
    finally:
        release.set()
        await asyncio.gather(tick, return_exceptions=True)
        await asyncio.wait_for(finished.wait(), timeout=2)


@pytest.mark.asyncio
async def test_cancelled_tick_does_not_construct_coroutines_for_waiting_rows(monkeypatch):
    constructed = active = 0
    full, release = asyncio.Event(), asyncio.Event()

    def work(_row):
        nonlocal constructed
        constructed += 1

        async def run():
            nonlocal active
            active += 1
            if active == arq_app.TICK_CONCURRENCY:
                full.set()
            try:
                await release.wait()
            finally:
                active -= 1

        return run()

    async def events(_s):
        return list(range(20))

    async def hooks(_s):
        return []

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(arq_app, "session_factory", lambda: session)
    monkeypatch.setattr(arq_app, "claim_batch", events)
    monkeypatch.setattr(arq_app, "claim_webhook_batch", hooks)
    monkeypatch.setattr(arq_app, "process_event", work)
    ctx = {"redis": _Redis(), "poll_tick_lock": asyncio.Lock()}
    tick = asyncio.create_task(arq_app.poll_tick(ctx))
    try:
        await asyncio.wait_for(full.wait(), timeout=2)
        assert constructed == arq_app.TICK_CONCURRENCY
        tick.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tick
        assert active == 0
        assert not ctx["poll_tick_lock"].locked()
    finally:
        release.set()
        await asyncio.gather(tick, return_exceptions=True)
