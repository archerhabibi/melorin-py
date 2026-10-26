"""Pictures in support tickets: the customer sends a photo while writing a ticket, and the support team's pictures reach the chat."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner import TelegramRunner  # noqa: E402
from tgmain.client import Ctx  # noqa: E402
from tgmain.errors import CoreError  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("MELORIN_CORE_URL", "http://core.invalid")
    monkeypatch.setenv("MELORIN_BOT_SERVICE_SECRET", "x" * 32)
    r = TelegramRunner(token="123:abc", offset_file=tmp_path / "offset.json")
    r.sent, r.photos, r.api_calls = [], [], []

    async def store_info():
        return {"id": "s1"}

    async def tg(method, payload):
        assert method == "getFile"
        return {"file_path": "photos/p.jpg", "file_size": len(JPEG)}

    async def download(url, **kw):
        return SimpleNamespace(content=JPEG, raise_for_status=lambda: None)

    async def send(chat_id, text, rows=None, *, reply=False, html=False):
        r.sent.append(text)

    async def send_photo(
        chat_id, data, caption, rows=None, *, filename="qr.png", mime="image/png"
    ):
        r.photos.append((data, caption, mime))

    async def api(ctx, method, path, **kw):
        r.api_calls.append((method, path, kw))
        if path.endswith("/tickets/attachments"):
            return {"id": "img-1", "content_type": "image/jpeg", "size": len(JPEG)}
        if path.endswith("/tickets"):
            return {"id": "t1", "number": "T-1", "subject": kw["json"]["subject"]}
        return {}

    r.store_info, r.tg, r.send, r.send_photo, r.api = (
        store_info,
        tg,
        send,
        send_photo,
        api,
    )
    r.client.get = download
    return r


def ctx():
    return Ctx(42, {"id": 42, "first_name": "علی"}, {"access_token": "tok"}, 1)


def photo(caption=None):
    m = {"chat": {"id": 42}, "photo": [{"file_id": "small"}, {"file_id": "big"}]}
    if caption:
        m["caption"] = caption
    return m


@pytest.mark.asyncio
async def test_photo_while_writing_a_new_ticket_becomes_the_ticket(runner):
    runner._set_state(42, {"new_ticket_subject": "اتصال برقرار نمی‌شود"})
    await runner.on_file(ctx(), photo("اسکرین‌شات خطا"))
    upload, create = runner.api_calls
    assert upload[1] == "/api/v1/stores/s1/tickets/attachments"
    assert upload[2]["files"]["file"] == ("ticket-image", JPEG, "image/jpeg")
    assert create[1] == "/api/v1/stores/s1/tickets"
    assert create[2]["json"] == {
        "subject": "اتصال برقرار نمی‌شود",
        "body": "اسکرین‌شات خطا",
        "attachment_id": "img-1",
    }
    assert "T-1" in runner.sent[-1]
    assert runner.state.get("42") is None  # the flow is finished


@pytest.mark.asyncio
async def test_photo_without_caption_is_a_picture_only_message(runner):
    runner._set_state(42, {"reply_ticket": "t9"})
    await runner.on_file(ctx(), photo())
    _, reply = runner.api_calls
    assert reply[1] == "/api/v1/tickets/t9/messages"
    assert reply[2]["json"] == {"body": "", "attachment_id": "img-1"}
    assert runner.state.get("42") is None


@pytest.mark.asyncio
async def test_plain_text_still_works_without_a_picture(runner):
    runner._set_state(42, {"reply_ticket": "t9"})
    await runner.on_text(ctx(), "سلام")
    assert runner.api_calls == [
        ("POST", "/api/v1/tickets/t9/messages", {"json": {"body": "سلام"}})
    ]


@pytest.mark.asyncio
async def test_a_non_image_document_is_refused_before_anything_is_uploaded(runner):
    runner._set_state(42, {"reply_ticket": "t9"})
    message = {
        "chat": {"id": 42},
        "document": {
            "file_id": "d",
            "mime_type": "application/pdf",
            "file_name": "a.pdf",
        },
    }
    await runner.on_file(ctx(), message)
    assert runner.api_calls == []
    assert "فقط تصویر" in runner.sent[-1]
    assert runner.state["42"] == {
        "reply_ticket": "t9"
    }  # still waiting for a valid message


@pytest.mark.asyncio
async def test_an_oversized_picture_is_refused(runner, monkeypatch):
    monkeypatch.setenv("MELORIN_MAX_UPLOAD_BYTES", "4")
    runner._set_state(42, {"reply_ticket": "t9"})
    await runner.on_file(ctx(), photo())
    assert runner.api_calls == []
    assert "حجم تصویر" in runner.sent[-1]


@pytest.mark.asyncio
async def test_receipt_flow_is_unchanged(runner):
    """Without a ticket in progress a file is still a payment receipt."""
    await runner.on_file(ctx(), photo())
    assert runner.api_calls == []
    assert "/topup" in runner.sent[-1]


@pytest.mark.asyncio
async def test_thread_view_sends_support_pictures_and_marks_customer_ones(runner):
    messages = [
        {"id": "m1", "is_staff": False, "body": "", "attachment_id": "a1"},
        {
            "id": "m2",
            "is_staff": True,
            "body": "این را امتحان کنید",
            "attachment_id": "a2",
        },
        {"id": "m3", "is_staff": True, "body": "متن بدون عکس"},
    ]

    async def api(c, method, path, **kw):
        if path == "/api/v1/tickets/t1":
            return {
                "id": "t1",
                "number": "T-1",
                "subject": "مشکل",
                "status": "answered",
            }
        if path == "/api/v1/tickets/t1/messages":
            return messages
        raise AssertionError(path)

    async def api_file(c, path):
        assert (
            path == "/api/v1/tickets/t1/messages/m2/attachment"
        )  # only the support picture is fetched
        return JPEG, "image/jpeg"

    shown = []

    async def screen(c, text, rows=None):
        shown.append(text)

    runner.api, runner.api_file, runner.screen = api, api_file, screen
    await runner.cb_ticket(ctx(), "t1")
    assert (
        shown[0].count("🖼 تصویر پیوست") == 2
    )  # both pictures are marked in the text ...
    assert len(runner.photos) == 1  # ... but only the support team's is sent as a photo
    data, caption, mime = runner.photos[0]
    assert (data, mime) == (JPEG, "image/jpeg")
    assert "این را امتحان کنید" in caption


@pytest.mark.asyncio
async def test_a_missing_picture_does_not_hide_the_thread(runner):
    async def api(c, method, path, **kw):
        if path == "/api/v1/tickets/t1":
            return {"id": "t1", "number": "T-1", "subject": "مشکل", "status": "open"}
        return [{"id": "m2", "is_staff": True, "body": "x", "attachment_id": "a2"}]

    async def api_file(c, path):
        raise CoreError(404, "تصویر پیدا نشد", "NOT_FOUND")

    shown = []

    async def screen(c, text, rows=None):
        shown.append(text)

    runner.api, runner.api_file, runner.screen = api, api_file, screen
    await runner.cb_ticket(ctx(), "t1")
    assert shown and runner.photos == []
