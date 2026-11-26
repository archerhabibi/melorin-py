"""Mandatory channel membership in the main bot: Core's CHANNEL_JOIN_REQUIRED becomes a join screen, "✅ I joined" re-asks
Core (pop-up when still missing), and a /start deep link that arrived while gated is replayed after joining."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner import TelegramRunner  # noqa: E402
from tgmain.ui import JOIN_CHECK_BUTTON, JOIN_CHECK_DATA, JOIN_NOT_YET, join_rows  # noqa: E402

CHANNELS = [{"title": "اخبار <ملورین>", "url": "https://t.me/melorin_news"}, {"title": "VIP", "url": "https://t.me/+AbCdEfGh123"}]


class World:
    def __init__(self):
        self.joined = False
        self.telegram: list[tuple[str, dict]] = []
        self.logins: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.telegram.org" in url:
            method = url.rsplit("/", 1)[1]
            self.telegram.append((method, json.loads(request.content or b"{}")))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        path = request.url.path
        if path == "/api/v1/stores/main":
            return httpx.Response(200, json={"id": "s1", "name": "Main"})
        if path == "/api/v1/telegram/button-styles":
            return httpx.Response(200, json={"enabled": False, "inline": [], "reply": []})
        if path == "/api/v1/auth/telegram/bot":
            self.logins.append(json.loads(request.content))
            if not self.joined:
                return httpx.Response(
                    403,
                    json={"error": {"code": "CHANNEL_JOIN_REQUIRED", "message": "اول عضو شوید", "details": {"channels": CHANNELS}}},
                )
            return httpx.Response(200, json={"access_token": "a", "refresh_token": "r"})
        return httpx.Response(500, json={})  # the home card is best effort; any Core call after login is not under test

    def sent(self, method: str) -> list[dict]:
        return [p for m, p in self.telegram if m == method]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("MELORIN_CORE_URL", "http://core.invalid")
    monkeypatch.setenv("MELORIN_BOT_SERVICE_SECRET", "x" * 32)
    w = World()
    bot = TelegramRunner(token="123:abc", offset_file=tmp_path / "offset.json")
    bot.client = httpx.AsyncClient(transport=httpx.MockTransport(w.handler))
    w.bot = bot
    return w


def _message(text, uid=1):
    return {"update_id": uid, "message": {"message_id": 50, "chat": {"id": 9}, "from": {"id": 7, "first_name": "A"}, "text": text}}


def _check(uid=2):
    return {
        "update_id": uid,
        "callback_query": {"id": "cb1", "data": JOIN_CHECK_DATA, "from": {"id": 7}, "message": {"message_id": 60, "chat": {"id": 9}}},
    }


def test_join_rows_list_each_channel_then_the_check_button():
    rows = join_rows(CHANNELS)
    assert rows[0] == [("📢 اخبار <ملورین>", "https://t.me/melorin_news")]
    assert rows[-1] == [(JOIN_CHECK_BUTTON, JOIN_CHECK_DATA)]


def test_gated_user_gets_the_join_screen_with_url_buttons(world):
    asyncio.run(world.bot.handle(_message("/plans")))
    (msg,) = world.sent("sendMessage")
    assert msg["chat_id"] == 9 and "اول عضو شوید" in msg["text"] and msg["parse_mode"] == "HTML"
    buttons = [b for row in msg["reply_markup"]["inline_keyboard"] for b in row]
    assert [b.get("url") for b in buttons[:2]] == ["https://t.me/melorin_news", "https://t.me/+AbCdEfGh123"]
    assert buttons[2]["callback_data"] == JOIN_CHECK_DATA


def test_check_while_still_missing_shows_a_popup_and_sends_nothing(world):
    asyncio.run(world.bot.handle(_check()))
    answers = world.sent("answerCallbackQuery")
    assert answers == [{"callback_query_id": "cb1", "text": JOIN_NOT_YET, "show_alert": True}]  # answered once, with the reason
    assert world.sent("sendMessage") == []


def test_deep_link_is_kept_while_gated_and_replayed_after_joining(world):
    asyncio.run(world.bot.handle(_message("/start link_ABC123")))
    assert world.bot.state["9"]["join_start"] == "link_ABC123"
    replayed = []

    async def cmd_start(ctx, arg):
        replayed.append(arg)

    world.bot.cmd_start = cmd_start
    world.joined = True
    asyncio.run(world.bot.handle(_check()))
    assert replayed == ["link_ABC123"]
    assert "join_start" not in (world.bot.state.get("9") or {})
    assert world.sent("deleteMessage") == [{"chat_id": 9, "message_id": 60}]  # the join screen goes away
    confirmed = world.sent("answerCallbackQuery")
    assert len(confirmed) == 1 and "تأیید" in confirmed[0]["text"]


def test_referral_start_is_still_sent_to_core_while_gated(world):
    asyncio.run(world.bot.handle(_message("/start ref_FRIEND")))
    assert world.logins[0]["referral_code"] == "FRIEND"  # Core records the referral before refusing the session


def test_members_are_not_bothered(world):
    world.joined = True
    asyncio.run(world.bot.handle(_message("/help")))
    texts = [m["text"] for m in world.sent("sendMessage")]
    assert texts and not any("اول عضو شوید" in t for t in texts)
