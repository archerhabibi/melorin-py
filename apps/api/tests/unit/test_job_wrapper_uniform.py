"""All 23 worker jobs go through the one shared ``tracked_job`` wrapper (audit P5); it never alters results or errors."""

import asyncio
import inspect

import pytest

from melorin.core import metrics
from melorin.worker import arq_app, jobs, wrap
from melorin.worker.wrap import tracked_job


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def eval(self, _script, _n, key, token):
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(wrap, "get_redis", lambda: r)
    return r


def _all_jobs():
    return [n for n, f in inspect.getmembers(jobs, inspect.iscoroutinefunction) if n.endswith("_job")]


def test_every_job_and_poll_tick_is_wrapped():
    names = _all_jobs()
    assert len(names) == 23
    assert all(hasattr(getattr(jobs, n), "__wrapped__") for n in names), names
    assert hasattr(arq_app.poll_tick, "__wrapped__")  # 23 jobs + poll_tick (refund_recovery_job added by the durable refund workflow)


@pytest.mark.asyncio
async def test_result_and_error_pass_through():
    @tracked_job
    async def ok_job(ctx=None):
        return 7

    @tracked_job
    async def bad_job(ctx=None):
        raise ValueError("boom")

    assert await ok_job() == 7
    with pytest.raises(ValueError):
        await bad_job()


@pytest.mark.asyncio
async def test_lock_skips_overlap_and_is_released(fake_redis):
    started, release = asyncio.Event(), asyncio.Event()

    @tracked_job
    async def slow_job(ctx=None):
        started.set()
        await release.wait()
        return "done"

    first = asyncio.create_task(slow_job())
    await started.wait()
    assert await slow_job() is None  # overlapping run is skipped, not queued
    release.set()
    assert await first == "done"
    assert fake_redis.store == {}  # lock released
    assert await slow_job() == "done"  # and the next run can start


@pytest.mark.asyncio
async def test_lock_fails_closed_when_redis_breaks_and_records_metric(monkeypatch):
    metrics.reset()
    calls = 0

    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(wrap, "get_redis", boom)

    @tracked_job
    async def x_job(ctx=None):
        nonlocal calls
        calls += 1
        return 1

    with pytest.raises(wrap.JobLockUnavailableError):
        await x_job()
    assert calls == 0
    assert 'melorin_job_runs_total{job="x_job",outcome="lock_error"}' in metrics.render()


@pytest.mark.asyncio
async def test_lock_fails_closed_when_redis_is_not_configured(monkeypatch):
    monkeypatch.setattr(wrap, "get_redis", lambda: None)

    @tracked_job
    async def x_job(ctx=None):
        return 1

    with pytest.raises(wrap.JobLockUnavailableError, match="not configured"):
        await x_job()


@pytest.mark.asyncio
async def test_timeout_and_metrics(fake_redis):
    metrics.reset()

    @tracked_job(timeout=0.05)
    async def hang_job(ctx=None):
        await asyncio.sleep(5)

    with pytest.raises(TimeoutError):
        await hang_job()
    assert fake_redis.store == {}
    out = metrics.render()
    assert 'melorin_job_runs_total{job="hang_job",outcome="timeout"}' in out
