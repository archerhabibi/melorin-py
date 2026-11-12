"""Admin-configured button styling in the bots: applied to keyboards, safe for the reply menu, refreshed from Core,
and never allowed to lose a message when Telegram refuses a style / Premium emoji."""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner import TelegramRunner  # noqa: E402
from tgmain import ui  # noqa: E402

TOKEN = "123456789:" + "A" * 35
PROJECTION = {
    "enabled": True,
    "inline": [
        {"key": "menu:plans", "match": "exact", "style": "success", "prefix": "💎 "},
        {"key": "menu:", "match": "prefix", "style": "primary", "icon": "5368324170671202286"},
        {"key": "@url", "match": "exact", "style": "primary"},
    ],
    "reply": [{"key": "🛒 خرید اکانت", "match": "exact", "style": "success", "icon": "12345678"}],
}


@pytest.fixture(autouse=True)
def _reset():
    ui.set_button_styles(None)
    yield
    ui.set_button_styles(None)


def test_disabled_keyboards_are_byte_identical_to_before():
    assert ui.keyboard([[("🛒 خرید", "menu:plans"), ("لینک", "https://x.example/a")]]) == {
        "inline_keyboard": [[{"text": "🛒 خرید", "callback_data": "menu:plans"}, {"text": "لینک", "url": "https://x.example/a"}]]
    }
    assert ui.reply_keyboard([["a", "b"]]) == {"keyboard": [[{"text": "a"}, {"text": "b"}]], "resize_keyboard": True}


def test_inline_buttons_get_style_icon_decoration_and_urls_use_the_pseudo_key():
    ui.set_button_styles(PROJECTION)
    rows = ui.keyboard([[("خرید", "menu:plans"), ("کیف پول", "menu:wallet")], [("سایت", "https://x.example/a"), ("بی‌رنگ", "other:1")]])
    a, b = rows["inline_keyboard"][0]
    assert a == {"text": "💎 خرید", "style": "success", "callback_data": "menu:plans"}
    assert b == {"text": "کیف پول", "style": "primary", "icon_custom_emoji_id": "5368324170671202286", "callback_data": "menu:wallet"}
    c, d = rows["inline_keyboard"][1]
    assert c == {"text": "سایت", "style": "primary", "url": "https://x.example/a"}
    assert d == {"text": "بی‌رنگ", "callback_data": "other:1"}


def test_reply_menu_text_never_changes():
    ui.set_button_styles(PROJECTION)
    kb = ui.reply_keyboard(ui.MAIN_MENU)
    first = kb["keyboard"][0][0]
    assert first == {"text": "🛒 خرید اکانت", "style": "success", "icon_custom_emoji_id": "12345678"}
    assert [b["text"] for row in kb["keyboard"] for b in row] == [t for row in ui.MAIN_MENU for t in row]


@pytest.mark.parametrize("junk", [None, {}, {"enabled": False}, {"enabled": True}, {"enabled": True, "inline": 1, "reply": []}, "x"])
def test_malformed_projection_switches_styling_off(junk):
    ui.set_button_styles(PROJECTION)
    ui.set_button_styles(junk)
    assert ui.keyboard([[("a", "menu:plans")]])["inline_keyboard"][0][0] == {"text": "a", "callback_data": "menu:plans"}


def test_long_label_is_not_pushed_past_the_limit_by_decoration():
    ui.set_button_styles(PROJECTION)
    long = "x" * ui.MAX_BUTTON_TEXT
    assert ui.keyboard([[(long, "menu:plans")]])["inline_keyboard"][0][0]["text"] == long


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("MELORIN_CORE_URL", "http://core.invalid")
    monkeypatch.setenv("MELORIN_BOT_SERVICE_SECRET", "x" * 32)
    from tgmain.client import TransportMixin

    monkeypatch.setattr(TransportMixin, "_styles_at", 0.0)
    return TelegramRunner(token=TOKEN, offset_file=tmp_path / "offset.json")


@pytest.mark.asyncio
async def test_refresh_downloads_once_per_interval_and_keeps_old_styles_on_failure(runner):
    calls = []
    answers = [httpx.Response(200, json=PROJECTION), httpx.Response(200, json={"enabled": False, "inline": [], "reply": []})]

    def handler(request):
        calls.append(str(request.url))
        return answers.pop(0)

    runner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await runner.refresh_button_styles()
    await runner.refresh_button_styles()  # inside the interval: no second request
    assert calls == ["http://core.invalid/api/v1/telegram/button-styles"]
    assert ui.keyboard([[("a", "menu:plans")]])["inline_keyboard"][0][0]["style"] == "success"

    runner.STYLE_REFRESH_SECONDS = 0
    runner.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))))
    await runner.refresh_button_styles()  # Core unreachable: previous styling stays
    assert "style" in ui.keyboard([[("a", "menu:plans")]])["inline_keyboard"][0][0]


@pytest.mark.asyncio
async def test_refused_styled_buttons_are_resent_plain(runner):
    ui.set_button_styles(PROJECTION)
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "style" in json.dumps(body):
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: DOCUMENT_INVALID"})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    runner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await runner.send(5, "hi", [[("خرید", "menu:plans")]])
    assert len(bodies) == 2
    assert bodies[1]["reply_markup"] == {"inline_keyboard": [[{"text": "💎 خرید", "callback_data": "menu:plans"}]]}


@pytest.mark.asyncio
async def test_not_modified_is_not_retried_and_plain_400_still_raises(runner):
    ui.set_button_styles(PROJECTION)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: message is not modified"})

    runner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await runner.tg("editMessageText", {"reply_markup": ui.keyboard([[("a", "menu:plans")]])})
    assert len(calls) == 1


# ---- review fixes ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "junk",
    [
        {"enabled": True, "inline": ["oops"], "reply": [None, 5]},
        {"enabled": True, "inline": [{"key": None, "match": "exact", "style": "primary"}], "reply": []},
        {"enabled": True, "inline": [{"key": "menu:", "match": "regex", "style": "primary"}], "reply": []},
        {"enabled": True, "inline": [{"key": "menu:", "match": "prefix"}], "reply": []},
    ],
)
def test_a_bad_rule_is_dropped_and_never_breaks_keyboards(junk):
    """Every menu is built through these helpers: a malformed download must not raise (it used to AttributeError)."""
    ui.set_button_styles(junk)
    assert ui.keyboard([[("a", "menu:plans")]])["inline_keyboard"][0][0] == {"text": "a", "callback_data": "menu:plans"}
    assert ui.reply_keyboard([["a"]])["keyboard"][0][0] == {"text": "a"}


def test_unknown_colour_or_non_numeric_icon_never_reaches_telegram():
    ui.set_button_styles(
        {"enabled": True, "inline": [{"key": "menu:", "match": "prefix", "style": "purple", "icon": "abc", "prefix": "★ "}], "reply": []}
    )
    assert ui.keyboard([[("a", "menu:plans")]])["inline_keyboard"][0][0] == {"text": "★ a", "callback_data": "menu:plans"}
    ui.set_button_styles({"enabled": True, "inline": [{"key": "menu:", "match": "prefix", "style": "danger", "icon": "12345678"}], "reply": []})
    assert ui.keyboard([[("a", "menu:plans")]])["inline_keyboard"][0][0]["style"] == "danger"


@pytest.mark.asyncio
async def test_failed_download_is_retried_soon_not_after_a_whole_interval(runner):
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("core not up yet")

    runner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    runner.STYLE_REFRESH_SECONDS = 60.0
    runner.STYLE_RETRY_SECONDS = 10.0
    await runner.refresh_button_styles()
    from tgmain.client import TransportMixin

    TransportMixin._styles_at -= 11  # ten seconds later
    await runner.refresh_button_styles()
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("description", ["Bad Request: message to edit not found", "Bad Request: can't parse entities: x", "Bad Request: chat not found"])
async def test_unrelated_400_is_not_retried_as_if_it_were_a_style_problem(runner, description):
    ui.set_button_styles(PROJECTION)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"ok": False, "description": description})

    runner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await runner.tg("sendMessage", {"reply_markup": ui.keyboard([[("a", "menu:plans")]])})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_non_json_error_body_is_still_retried_plain(runner):
    ui.set_button_styles(PROJECTION)
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        if "style" in json.dumps(bodies[-1]):
            return httpx.Response(400, content=b"<html>bad gateway-ish</html>")
        return httpx.Response(200, json={"ok": True, "result": {}})

    runner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await runner.send(5, "hi", [[("خرید", "menu:plans")]])
    assert len(bodies) == 2 and "style" not in json.dumps(bodies[1])


@pytest.mark.asyncio
async def test_error_body_that_is_not_an_object_does_not_crash_the_fallback(runner):
    ui.set_button_styles(PROJECTION)

    def handler(request):
        return httpx.Response(400, json=["unexpected"])

    runner.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):  # the second (plain) attempt fails the same way and is reported, not an AttributeError
        await runner.tg("sendMessage", {"reply_markup": ui.keyboard([[("a", "menu:plans")]])})
