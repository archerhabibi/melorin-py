"""/reseller in the main bot: request first, domain + bot token only after the admin approved (Telegram and Core mocked)."""

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]
TOKEN = "123456789:" + "A" * 35


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Fake:
    def __init__(self):
        self.sent, self.deleted, self.posts = [], [], []
        self.apps = []  # what GET /reseller/applications returns
        self.details_reply = (200, {"store_name": "Shop", "domain": "shop.example.com", "bot_username": "shopbot", "status": "approved"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, body = str(request.url), (request.content or b"")
        if "api.telegram.org" in url:
            if url.endswith("/sendMessage"):
                self.sent.append(json.loads(body))
            if url.endswith("/deleteMessage"):
                self.deleted.append(json.loads(body))
            return httpx.Response(200, json={"ok": True, "result": {}})
        path = request.url.path
        if path == "/api/v1/stores/main":
            return httpx.Response(200, json={"id": "s1", "name": "Main"})
        if path == "/api/v1/auth/telegram/bot":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R"})
        if path == "/api/v1/reseller/applications" and request.method == "GET":
            return httpx.Response(200, json=self.apps)
        if request.method == "POST":
            self.posts.append((path, json.loads(body) if body else None))
            if path.endswith("/details"):
                code, payload = self.details_reply
                return httpx.Response(code, json=payload)
            return httpx.Response(200, json={"id": "a1", "status": "pending"})
        return httpx.Response(404, json={})


@pytest.fixture
def bot(tmp_path, monkeypatch):
    for k, v in {
        "MELORIN_TELEGRAM_TOKEN": "tok",
        "MELORIN_CORE_URL": "http://core",
        "MELORIN_BOT_SERVICE_SECRET": "sek",
        "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "o.json"),
    }.items():
        monkeypatch.setenv(k, v)
    mod = load("tg_main_reseller", "telegram-main/runner.py")
    r, fake = mod.TelegramRunner(), Fake()
    r.client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return r, fake, tmp_path


_uid = iter(range(1, 1000))


def say(r, text, mid=None):
    update = {
        "update_id": next(_uid),
        "message": {"chat": {"id": 9}, "from": {"id": 7, "first_name": "A"}, "text": text, "message_id": mid or next(_uid) + 5000},
    }
    asyncio.run(r.handle(update))


def last(fake):
    return fake.sent[-1]["text"]


def app(status, **kw):
    return {"id": "a1", "target_store_id": "s1", "store_name": "Shop", "status": status, **kw}


def test_new_request_collects_name_and_message_then_files_application(bot):
    r, fake, _ = bot
    say(r, "/reseller")
    assert "نام فروشگاه" in last(fake) and r.state["9"] == {"rs": "name"}
    say(r, "ف")  # too short: asked again, state unchanged
    assert r.state["9"] == {"rs": "name"}
    say(r, "فروشگاه من")
    assert r.state["9"] == {"rs": "msg", "rs_name": "فروشگاه من"}
    say(r, "-")
    assert fake.posts == [("/api/v1/reseller/applications", {"store_name": "فروشگاه من", "message": None, "target_store_id": "s1"})]
    assert "ثبت شد" in last(fake) and "9" not in r.state
    assert not any("domain" in (b or {}) or "bot_token" in (b or {}) for _, b in fake.posts)  # nothing sensitive asked yet


def test_menu_button_starts_the_same_flow(bot):
    r, fake, _ = bot
    say(r, "🤖 درخواست ربات نماینده و همکاری")
    assert r.state["9"] == {"rs": "name"}


def test_pending_request_shows_status_and_can_be_cancelled(bot):
    r, fake, _ = bot
    fake.apps = [app("pending")]
    say(r, "/reseller")
    assert "در حال بررسی" in last(fake) and "9" not in r.state
    assert fake.sent[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "rsc:a1"
    asyncio.run(
        r.handle(
            {
                "update_id": 777,
                "callback_query": {"id": "c1", "from": {"id": 7}, "data": "rsc:a1", "message": {"chat": {"id": 9}, "message_id": 5}},
            }
        )
    )
    assert fake.posts[-1][0] == "/api/v1/reseller/applications/a1/cancel"


def test_rejected_request_shows_reason_and_allows_a_new_one(bot):
    r, fake, _ = bot
    fake.apps = [app("rejected", review_reason="دامنه نامعتبر")]
    say(r, "/reseller")
    assert "دامنه نامعتبر" in last(fake) and r.state["9"] == {"rs": "name"}


def test_after_approval_domain_then_token_creates_store_and_deletes_token_message(bot):
    r, fake, tmp = bot
    fake.apps = [app("awaiting_details")]
    say(r, "/reseller")
    assert "تأیید شده" in last(fake) and r.state["9"] == {"rs": "domain", "rs_app": "a1"}
    say(r, "shop.example.com")
    assert r.state["9"]["rs"] == "token" and "توکن" in last(fake)
    say(r, TOKEN, mid=4242)
    assert fake.posts[-1] == ("/api/v1/reseller/applications/a1/details", {"domain": "shop.example.com", "bot_token": TOKEN})
    assert fake.deleted == [{"chat_id": 9, "message_id": 4242}]  # the token never stays in the chat
    assert "ساخته شد" in last(fake) and "shopbot" in last(fake) and "9" not in r.state
    # the secret is neither echoed back nor persisted by the runner
    assert TOKEN not in json.dumps(fake.sent)
    assert all(TOKEN not in p.read_text() for p in tmp.iterdir() if p.is_file())


def test_token_errors_keep_domain_and_domain_errors_restart_at_domain(bot):
    r, fake, tmp = bot
    fake.apps = [app("awaiting_details")]
    say(r, "/reseller")
    say(r, "shop.example.com")
    fake.details_reply = (422, {"error": {"code": "BOT_TOKEN_REJECTED", "message": "تلگرام این توکن را نپذیرفت"}})
    say(r, TOKEN, mid=11)
    assert "نپذیرفت" in last(fake) and r.state["9"]["rs"] == "token" and r.state["9"]["rs_domain"] == "shop.example.com"
    assert fake.deleted[-1]["message_id"] == 11  # deleted even though the token was rejected
    fake.details_reply = (409, {"error": {"code": "DOMAIN_TAKEN", "message": "این دامنه قبلاً ثبت شده"}})
    say(r, TOKEN, mid=12)
    assert r.state["9"] == {"rs": "domain", "rs_app": "a1"} and "دامنه را دوباره" in last(fake)
    assert TOKEN not in json.dumps(fake.sent) and all(TOKEN not in p.read_text() for p in tmp.iterdir() if p.is_file())


def test_unexpected_core_error_ends_the_flow(bot):
    r, fake, _ = bot
    fake.apps = [app("awaiting_details")]
    say(r, "/reseller")
    say(r, "shop.example.com")
    fake.details_reply = (
        409,
        {"error": {"code": "APPLICATION_NOT_AWAITING_DETAILS", "message": "این درخواست در مرحلهٔ دریافت اطلاعات نیست."}},
    )
    say(r, TOKEN, mid=13)
    assert "9" not in r.state and "نیست" in last(fake)


def test_cancel_command_clears_the_flow(bot):
    r, fake, _ = bot
    say(r, "/reseller")
    say(r, "/cancel")
    assert "9" not in r.state


def test_reseller_channel_keeps_the_ticket_request(bot):
    r, fake, _ = bot
    r.channel = "reseller"
    say(r, "/reseller")
    assert r.state["9"] == {"new_ticket_subject": "🤖 درخواست ربات نماینده و همکاری"} and fake.posts == []
