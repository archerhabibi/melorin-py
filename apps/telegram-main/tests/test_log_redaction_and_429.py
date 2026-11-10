import asyncio
import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tgmain.client import TransportMixin  # noqa: E402
from tgmain.logsafe import RedactTokens  # noqa: E402

TOKEN = "123456789:AAH_abcdefghijklmnopqrstuvwxyz012345"  # pragma: allowlist secret


def test_filter_redacts_message_args_and_traceback():
    try:
        raise RuntimeError(f"https://api.telegram.org/bot{TOKEN}/getUpdates")
    except RuntimeError as exc:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed: %s", (exc,), sys.exc_info())
    RedactTokens().filter(record)
    rendered = logging.Formatter().format(record)
    assert TOKEN not in rendered
    assert "bot<redacted>" in rendered


class _Bot(TransportMixin):
    token = TOKEN

    def __init__(self, handler):
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_429_honours_retry_after_then_succeeds(monkeypatch):
    calls, slept = [], []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 3}}, request=request)
        return httpx.Response(200, json={"ok": True, "result": [1]}, request=request)

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    assert asyncio.run(_Bot(handler).tg("getUpdates", {})) == [1]
    assert slept == [3.5] and len(calls) == 2  # retry_after + 0.5s margin (person3 client)


def test_429_gives_up_after_retries(monkeypatch):
    async def fake_sleep(seconds):
        pass

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    bot = _Bot(lambda req: httpx.Response(429, json={"parameters": {"retry_after": 1}}, request=req))
    try:
        asyncio.run(bot.tg("getUpdates", {}))
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 429
    else:
        raise AssertionError("expected HTTPStatusError")
