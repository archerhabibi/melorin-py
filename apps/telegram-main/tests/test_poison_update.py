"""A poisoned update must never freeze the long-poll loop for every user (head-of-line blocking)."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner import TelegramRunner  # noqa: E402


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("MELORIN_CORE_URL", "http://core.invalid")
    monkeypatch.setenv("MELORIN_BOT_SERVICE_SECRET", "x" * 32)
    return TelegramRunner(token="123:abc", offset_file=tmp_path / "offset.json")


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://core.invalid/x")
    return httpx.HTTPStatusError("boom", request=req, response=httpx.Response(code, request=req))


@pytest.mark.asyncio
async def test_permanent_4xx_is_dropped_and_acknowledged(runner):
    async def handle(update):
        raise _status_error(403)

    runner.handle = handle
    await runner._process_update({"update_id": 10})
    assert runner.offset == 11


@pytest.mark.asyncio
async def test_handler_bug_is_dropped_not_fatal(runner):
    async def handle(update):
        raise TypeError("bug")

    runner.handle = handle
    await runner._process_update({"update_id": 20})
    assert runner.offset == 21


@pytest.mark.asyncio
async def test_transient_error_replays_then_drops_after_cap(runner):
    async def handle(update):
        raise _status_error(503)

    runner.handle = handle
    for _ in range(runner.MAX_UPDATE_ATTEMPTS - 1):
        with pytest.raises(httpx.HTTPStatusError):
            await runner._process_update({"update_id": 30})
        assert runner.offset is None  # not acknowledged: replayed
    await runner._process_update({"update_id": 30})
    assert runner.offset == 31


@pytest.mark.asyncio
async def test_telegram_ok_false_is_bounded(runner):
    async def handle(update):
        raise RuntimeError("query is too old")

    runner.handle = handle
    for _ in range(runner.MAX_UPDATE_ATTEMPTS - 1):
        with pytest.raises(RuntimeError):
            await runner._process_update({"update_id": 40})
    await runner._process_update({"update_id": 40})
    assert runner.offset == 41


@pytest.mark.asyncio
async def test_success_acknowledges(runner):
    async def handle(update):
        return None

    runner.handle = handle
    await runner._process_update({"update_id": 50})
    assert runner.offset == 51
