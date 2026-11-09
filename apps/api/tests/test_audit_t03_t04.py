"""Audit T03 (one getMe helper) and T04 (one payments notifier)."""

import pathlib

import httpx
import pytest

from melorin.channels.telegram.bot_api import probe_bot

TOKEN = "123456789:" + "A" * 35


def _transport(status: int, body):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status, text="not json")

    return httpx.MockTransport(handler), seen


async def test_probe_bot_returns_status_and_result():
    transport, seen = _transport(200, {"ok": True, "result": {"username": "melorin_bot", "is_bot": True}})
    status, me = await probe_bot(TOKEN, transport=transport)
    assert status == 200 and me["username"] == "melorin_bot"
    assert seen[0].endswith("/getMe")


async def test_probe_bot_rejected_token_has_empty_result():
    transport, _ = _transport(401, {"ok": False, "description": "Unauthorized"})
    status, me = await probe_bot(TOKEN, transport=transport)
    assert status == 401 and me == {}


async def test_probe_bot_non_json_raises_value_error():
    transport, _ = _transport(200, None)
    with pytest.raises(ValueError):
        await probe_bot(TOKEN, transport=transport)


async def test_probe_bot_reuses_caller_client():
    transport, seen = _transport(200, {"result": {"username": "x"}})
    async with httpx.AsyncClient(transport=transport) as client:
        await probe_bot(TOKEN, client=client)
        await probe_bot(TOKEN, client=client)
        assert not client.is_closed
    assert len(seen) == 2


async def test_reseller_verify_bot_tolerates_garbage_200():
    from melorin.modules.reseller.identity import verify_bot

    transport, _ = _transport(200, None)
    assert await verify_bot(TOKEN, transport=transport) is None


def test_no_private_payment_notify_copies_left():
    root = pathlib.Path(__file__).resolve().parents[1] / "melorin" / "modules" / "payments"
    for name in ("bank_sms.py", "provisional.py"):
        text = (root / name).read_text()
        assert "def _notify(" not in text, name
        assert "notify_store_payments" in text, name
