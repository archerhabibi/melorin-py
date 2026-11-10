"""T03: every Bot API call of one event loop goes through one pooled client."""

import httpx

from melorin.channels.telegram import bot_api
from melorin.channels.telegram.bot_api import TelegramApiError, TelegramChannel, close_shared_clients, shared_client


def _channel():
    return TelegramChannel("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "https://core.test", "main")


async def test_one_client_per_loop_and_reopened_after_close():
    a = shared_client()
    assert shared_client() is a
    await close_shared_clients()
    assert a.is_closed
    assert shared_client() is not a
    await close_shared_clients()


async def test_calls_reuse_pool_and_surface_retry_after(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/getChat"):
            return httpx.Response(429, json={"ok": False, "error_code": 429, "description": "slow", "parameters": {"retry_after": 7}})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    await close_shared_clients()
    bot_api._pools[__import__("asyncio").get_running_loop()] = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ch = _channel()
    assert (await ch.send_message(1, "hi"))["ok"]
    assert (await ch.call("sendMessage", {"chat_id": 1, "text": "x"}))["ok"]
    try:
        await ch.get_chat(1)
        raise AssertionError("expected TelegramApiError")
    except TelegramApiError as exc:
        assert exc.code == 429 and exc.retry_after == 7
    assert len(seen) == 3
    await close_shared_clients()
