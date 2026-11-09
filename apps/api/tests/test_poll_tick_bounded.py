"""Audit T27: poll_tick never runs more than TICK_CONCURRENCY outbox/webhook rows at the same time."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from melorin.worker import arq_app


class _Redis:
    async def set(self, *a, **k):
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

    out = await arq_app.poll_tick({"redis": _Redis()})
    assert out == {"events": 20, "deliveries": 20}
    assert 1 < peak <= arq_app.TICK_CONCURRENCY
