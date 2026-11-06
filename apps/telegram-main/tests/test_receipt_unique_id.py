"""The bot passes Telegram's file_unique_id with a payment receipt so Core can spot the same picture sent twice."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner import TelegramRunner  # noqa: E402
from tgmain.client import Ctx  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("MELORIN_CORE_URL", "http://core.invalid")
    monkeypatch.setenv("MELORIN_BOT_SERVICE_SECRET", "x" * 32)
    r = TelegramRunner(token="123:abc", offset_file=tmp_path / "offset.json")
    r.sent, r.api_calls, r.fail = [], [], None

    async def store_info():
        return {"id": "s1"}

    async def tg(method, payload):
        return {"file_path": "photos/p.jpg", "file_size": len(JPEG)}

    async def download(url, **kw):
        return SimpleNamespace(content=JPEG, raise_for_status=lambda: None)

    async def send(chat_id, text, rows=None, *, reply=False, html=False):
        r.sent.append(text)

    async def api(ctx, method, path, **kw):
        r.api_calls.append((method, path, kw))
        if r.fail:
            raise r.fail
        return {}

    r.store_info, r.tg, r.send, r.api = store_info, tg, send, api
    r.client.get = download
    r._set_state(42, {"receipt_payment": "pay-1"})
    return r


def ctx():
    return Ctx(42, {"id": 42, "first_name": "علی"}, {"access_token": "tok"}, 1)


@pytest.mark.asyncio
async def test_photo_receipt_sends_the_biggest_sizes_file_unique_id(runner):
    msg = {"chat": {"id": 42}, "photo": [{"file_id": "s", "file_unique_id": "u-small"}, {"file_id": "b", "file_unique_id": "u-big"}]}
    await runner.on_file(ctx(), msg)
    ((method, path, kw),) = runner.api_calls
    assert (method, path) == ("POST", "/api/v1/stores/s1/payments/pay-1/receipt")
    assert kw["files"]["file"] == ("receipt", JPEG, "image/jpeg") and kw["data"] == {"file_unique_id": "u-big"}
    assert "رسید دریافت شد" in runner.sent[-1]


@pytest.mark.asyncio
async def test_document_receipt_sends_its_file_unique_id(runner):
    msg = {"chat": {"id": 42}, "document": {"file_id": "d", "file_unique_id": "u-doc", "mime_type": "image/png"}}
    await runner.on_file(ctx(), msg)
    assert runner.api_calls[0][2]["data"] == {"file_unique_id": "u-doc"}


@pytest.mark.asyncio
async def test_missing_unique_id_sends_no_form_field(runner):
    await runner.on_file(ctx(), {"chat": {"id": 42}, "photo": [{"file_id": "b"}]})
    assert runner.api_calls[0][2]["data"] is None
