"""Telegram side of the website login (bot runner, Telegram and Core mocked) plus frontend/doc contracts."""

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from _source import read_source, read_web_source

ROOT = Path(__file__).parents[2]
PROJECT = ROOT.parent
API = ROOT / "api"
SID = "AbCdEfGhIjKlMnOp"


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Fake:
    """Records Telegram calls and answers the three Core endpoints used by the flow."""

    def __init__(self):
        self.tg, self.core = [], []
        self.decide_reply = {"result": "approved"}
        self.inspect_status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = json.loads(request.content) if request.content else {}
        if "api.telegram.org" in url:
            self.tg.append((url.rsplit("/", 1)[1], body))
            return httpx.Response(200, json={"ok": True, "result": {}})
        path = request.url.path
        self.core.append((path, body, dict(request.headers)))
        if path == "/api/v1/stores/main":
            return httpx.Response(200, json={"id": "store-1", "name": "Main"})
        if path == "/api/v1/auth/telegram/bot":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R"})
        if "/web/bot/" in path:
            assert request.headers["x-bot-secret"] == "sek"
        if path.endswith("/web/bot/inspect"):
            if self.inspect_status != 200:
                return httpx.Response(
                    self.inspect_status, json={"error": {"code": "SESSION_CLOSED", "message": "این درخواست ورود دیگر معتبر نیست."}}
                )
            return httpx.Response(
                200,
                json={
                    "status": "scanned",
                    "device": "Chrome · Windows",
                    "ip": "203.0.113.7",
                    "age_seconds": 12,
                    "expires_in": 150,
                    "number_match": True,
                    "choices": ["47", "12", "83"],
                },
            )
        if path.endswith("/web/bot/decide"):
            return httpx.Response(200, json=self.decide_reply)
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
    r, fake = load("tg_main_p01", "telegram-main/runner.py").TelegramRunner(), Fake()
    r.client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return r, fake


def start_msg(arg):
    return {
        "update_id": 1,
        "message": {"chat": {"id": 9}, "from": {"id": 7, "first_name": "Ali", "username": "ali"}, "text": f"/start {arg}"},
    }


def tap(data, uid=2):
    return {
        "update_id": uid,
        "callback_query": {
            "id": f"cb{uid}",
            "from": {"id": 7, "first_name": "Ali"},
            "data": data,
            "message": {"chat": {"id": 9}, "message_id": 55},
        },
    }


def last(fake, method):
    return [b for m, b in fake.tg if m == method][-1]


def buttons(markup):
    return [b for row in markup["inline_keyboard"] for b in row]


def test_start_link_shows_context_and_number_choices(bot):
    r, fake = bot
    asyncio.run(r.handle(start_msg(f"wl_{SID}")))
    path, body, headers = [c for c in fake.core if c[0].endswith("/web/bot/inspect")][0]
    assert body["session_id"] == SID and body["store_id"] == "store-1" and body["telegram_id"] == 7
    assert headers["x-bot-secret"] == "sek"
    sent = last(fake, "sendMessage")
    assert "Chrome · Windows" in sent["text"] and "203.0.113.7" in sent["text"] and "12 ثانیه" in sent["text"]
    data = [b["callback_data"] for b in buttons(sent["reply_markup"])]
    assert data == [f"wla:{SID}:47", f"wla:{SID}:12", f"wla:{SID}:83", f"wld:{SID}"]
    assert all(len(d.encode()) <= 64 for d in data)  # Telegram callback_data limit


def test_closed_session_is_explained_not_crashed(bot):
    r, fake = bot
    fake.inspect_status = 410
    asyncio.run(r.handle(start_msg(f"wl_{SID}")))
    assert "دیگر معتبر نیست" in last(fake, "sendMessage")["text"]


def test_choice_is_sent_to_core_and_screen_is_edited_in_place(bot):
    r, fake = bot
    asyncio.run(r.handle(tap(f"wla:{SID}:47")))
    _, body, _ = [c for c in fake.core if c[0].endswith("/web/bot/decide")][0]
    assert body["action"] == "approve" and body["choice"] == "47" and body["session_id"] == SID and body["telegram_id"] == 7
    edit = last(fake, "editMessageText")
    assert edit["message_id"] == 55 and "ورود تأیید شد" in edit["text"] and "reply_markup" not in edit


def test_wrong_choice_shows_remaining_attempts_and_new_choices(bot):
    r, fake = bot
    fake.decide_reply = {"result": "retry", "remaining": 1, "choices": ["83", "47", "12"]}
    asyncio.run(r.handle(tap(f"wla:{SID}:12")))
    edit = last(fake, "editMessageText")
    assert "1" in edit["text"] and "درست نبود" in edit["text"]
    assert [b["callback_data"] for b in buttons(edit["reply_markup"])][:3] == [f"wla:{SID}:83", f"wla:{SID}:47", f"wla:{SID}:12"]


def test_denied_outcomes_have_their_own_messages(bot):
    r, fake = bot
    fake.decide_reply = {"result": "denied", "reason": "too_many_wrong_choices"}
    asyncio.run(r.handle(tap(f"wla:{SID}:12")))
    assert "عدد اشتباه" in last(fake, "editMessageText")["text"]
    fake.decide_reply = {"result": "denied", "reason": "admin_use_panel"}
    asyncio.run(r.handle(tap(f"wla:{SID}:47", uid=3)))
    assert "پنل مدیریت" in last(fake, "editMessageText")["text"]


def test_not_me_button_denies(bot):
    r, fake = bot
    asyncio.run(r.handle(tap(f"wld:{SID}")))
    _, body, _ = [c for c in fake.core if c[0].endswith("/web/bot/decide")][0]
    assert body["action"] == "deny" and "choice" not in body or body.get("choice") is None
    assert "رد شد" in last(fake, "editMessageText")["text"]


def test_normal_start_and_link_flows_are_unchanged(bot):
    r, fake = bot
    asyncio.run(r.handle(start_msg("")))
    assert not [c for c in fake.core if "/web/bot/" in c[0]]
    assert "wla" in r.callbacks and "wld" in r.callbacks


def test_reseller_bot_inherits_the_flow_and_binds_its_own_store(tmp_path, monkeypatch):
    for k, v in {
        "MELORIN_TELEGRAM_RESELLER_TOKEN": "rt",
        "MELORIN_CORE_URL": "http://core",
        "MELORIN_BOT_SERVICE_SECRET": "sek",
        "MELORIN_STORE_SLUG": "shop1",
        "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "o.json"),
    }.items():
        monkeypatch.setenv(k, v)
    r = load("tg_res_p01", "telegram-reseller/runner.py").ResellerTelegramRunner()
    seen = []

    def h(request):
        seen.append((request.url.path, json.loads(request.content) if request.content else {}))
        if request.url.path.startswith("/api/v1/stores/by-slug/"):
            return httpx.Response(200, json={"id": "reseller-store", "name": "Shop"})
        return httpx.Response(
            200,
            json={
                "status": "scanned",
                "device": "d",
                "ip": "1.1.1.1",
                "age_seconds": 1,
                "expires_in": 100,
                "number_match": True,
                "choices": ["10", "20", "30"],
            },
        )

    r.client = httpx.AsyncClient(transport=httpx.MockTransport(h))
    r.tg = lambda method, payload: asyncio.sleep(0)  # no Telegram network
    ctx = load("tg_main_ctx", "telegram-main/runner.py").Ctx(9, {"id": 7, "first_name": "A"}, {"access_token": "A"}, 1)
    asyncio.run(r.cmd_web_login(ctx, SID))
    body = [b for p, b in seen if p.endswith("/web/bot/inspect")][0]
    assert body["store_id"] == "reseller-store"  # Core refuses links that were created for another store


# ---------------- contracts of the other pieces ----------------
def test_frontend_polls_with_post_body_and_keeps_nothing_in_storage():
    src = read_web_source(PROJECT / "apps/store-web/src/TelegramLogin.jsx")
    assert 'method: "POST"' in src and "poll_token: s.poll_token" in src
    assert "poll_token=" not in src and "?token" not in src  # secrets never travel in a URL
    assert "localStorage" not in src and "sessionStorage" not in src
    assert "/cancel" in src and "keepalive: true" in src  # closing the dialog invalidates the Telegram link
    assert 'rel="noopener noreferrer"' in src and "visibilitychange" in src
    app = read_web_source(PROJECT / "apps/store-web/src/App.jsx")
    assert 'import TelegramLogin from "./TelegramLogin.jsx"' in app and 'modal === "telegram"' in app
    assert "hasBot" in app and "store.bot_username" in app
    assert "pair.is_admin" in app  # admins still cannot keep a storefront session


def test_migration_and_model_agree_and_worker_cleans_up():
    mig = read_source(API / "alembic/versions/0019_telegram_web_login.py")
    assert 'down_revision = "0018_reseller_two_step"' in mig and "telegram_login_sessions" in mig
    from melorin.kernel.models.identity import TelegramLoginSession

    # The table is created by 0019 and extended by 0033 (automatic identity verification): together they cover the model.
    mig_trust = read_source(API / "alembic/versions/0033_trusted_devices.py")
    declared = set(__import__("re").findall(r'sa\.Column\("(\w+)"', mig + mig_trust))
    assert {c.name for c in TelegramLoginSession.__table__.columns} <= declared
    arq = read_source(API / "melorin/worker/arq_app.py")
    assert "cron(telegram_login_gc_job" in arq and "telegram_login_gc_job]" in arq
    assert "telegram_web_router" in read_source(API / "melorin/app.py")
