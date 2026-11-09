"""T20/T22/T40: the bot token never reaches the logs, and Telegram flood-waits (429 retry_after) are honoured."""

import io
import json
import logging
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner import TelegramRunner  # noqa: E402
from tgmain.logsafe import TOKEN_RE, RedactTokens, setup_bot_logging  # noqa: E402

TOKEN = "123456789:" + "A" * 35


def _logger(buf):
    handler = logging.StreamHandler(buf)
    handler.addFilter(RedactTokens())
    lg = logging.getLogger("melorin.test.t20")
    lg.handlers[:] = [handler]
    lg.propagate = False
    return lg


def test_http_status_error_traceback_is_redacted():
    buf = io.StringIO()
    lg = _logger(buf)
    req = httpx.Request("POST", f"https://api.telegram.org/bot{TOKEN}/getUpdates")
    try:
        httpx.Response(429, request=req).raise_for_status()
    except httpx.HTTPStatusError as exc:
        lg.exception("telegram cycle failed: %s", exc)  # exception object passed as an argument
    out = buf.getvalue()
    assert TOKEN not in out and "A" * 20 not in out and "bot<redacted>" in out


def test_stack_info_and_extra_args_are_redacted():
    buf = io.StringIO()
    lg = _logger(buf)
    lg.warning("url=%s n=%d", f"https://x/bot{TOKEN}/m", 3, stack_info=True)
    assert TOKEN not in buf.getvalue()


def test_httpx_logger_is_silenced_below_warning():
    setup_bot_logging("INFO")
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_bot_and_core_patterns_agree():
    from melorin.core.redact import TELEGRAM_TOKEN_RE

    assert TOKEN_RE.pattern == TELEGRAM_TOKEN_RE.pattern


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("MELORIN_CORE_URL", "http://core.invalid")
    monkeypatch.setenv("MELORIN_BOT_SERVICE_SECRET", "x" * 32)
    return TelegramRunner(token=TOKEN, offset_file=tmp_path / "offset.json")


def _with_transport(runner, responses, sleeps, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses.pop(0)

    runner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("tgmain.client.asyncio.sleep", fake_sleep)
    return calls


async def test_429_waits_retry_after_then_succeeds(runner, monkeypatch):
    sleeps = []
    responses = [
        httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 7}}),
        httpx.Response(200, json={"ok": True, "result": [{"update_id": 1}]}),
    ]
    calls = _with_transport(runner, responses, sleeps, monkeypatch)
    assert await runner.tg("getUpdates", {}) == [{"update_id": 1}]
    assert len(calls) == 2 and sleeps == [7.5]


async def test_429_gives_up_after_bounded_retries(runner, monkeypatch):
    sleeps = []
    responses = [httpx.Response(429, json={"parameters": {"retry_after": 1}}) for _ in range(10)]
    calls = _with_transport(runner, responses, sleeps, monkeypatch)
    with pytest.raises(httpx.HTTPStatusError):
        await runner.tg("getUpdates", {})
    assert len(calls) == runner.TG_MAX_RETRIES + 1


async def test_huge_retry_after_is_not_slept_inline(runner, monkeypatch):
    sleeps = []
    calls = _with_transport(runner, [httpx.Response(429, json={"parameters": {"retry_after": 3600}})], sleeps, monkeypatch)
    with pytest.raises(httpx.HTTPStatusError):
        await runner.tg("sendMessage", {})
    assert sleeps == [] and len(calls) == 1  # the caller's own backoff / replay policy takes over


async def test_non_429_errors_are_not_retried(runner, monkeypatch):
    sleeps = []
    calls = _with_transport(runner, [httpx.Response(400, json={"ok": False})], sleeps, monkeypatch)
    with pytest.raises(httpx.HTTPStatusError):
        await runner.tg("sendMessage", {})
    assert len(calls) == 1 and sleeps == []


def test_core_json_formatter_redacts_tracebacks():
    from melorin.core.logging import JsonFormatter

    try:
        raise RuntimeError(f"https://api.telegram.org/bot{TOKEN}/getUpdates")
    except RuntimeError:
        import sys as _s

        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, _s.exc_info())
    out = json.loads(JsonFormatter().format(rec))
    assert TOKEN not in json.dumps(out)
