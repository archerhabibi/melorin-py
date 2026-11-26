"""ADR-R3: the bot speaks in THIS store's name and never invents the platform's (or a guessed bot) on a store's behalf."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner import TelegramRunner  # noqa: E402
from tgmain.client import Ctx  # noqa: E402
from tgmain.ui import NEUTRAL_STORE_NAME, referral_text, store_display_name  # noqa: E402


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("MELORIN_CORE_URL", "http://core.invalid")
    monkeypatch.setenv("MELORIN_BOT_SERVICE_SECRET", "x" * 32)
    return TelegramRunner(token="123:abc", offset_file=tmp_path / "offset.json")


def _ctx():
    return Ctx(777, {"id": 777}, {"access_token": "t"}, 1)


@pytest.mark.parametrize(
    "store, expected",
    [
        ({"name": "Paris VPN"}, "Paris VPN"),
        ({"name": "  فروشگاه   پارس "}, "فروشگاه پارس"),
        ({"name": ""}, NEUTRAL_STORE_NAME),
        ({"name": None}, NEUTRAL_STORE_NAME),
        ({}, NEUTRAL_STORE_NAME),
        (None, NEUTRAL_STORE_NAME),
    ],
)
def test_store_display_name_is_the_stores_own_or_neutral(store, expected):
    assert store_display_name(store) == expected
    assert "ملورین" not in expected and "melorin" not in expected.lower()


async def _welcome(runner, store):
    shown = []

    async def store_info():
        return store

    async def send_main_menu(chat_id, text):
        shown.append(text)

    async def cmd_home(ctx, arg):
        return None

    runner.store_info, runner.send_main_menu, runner.cmd_home = store_info, send_main_menu, cmd_home
    await runner.cmd_start(_ctx(), "")
    return shown[0]


@pytest.mark.asyncio
async def test_welcome_greets_in_the_stores_name(runner):
    assert (await _welcome(runner, {"id": "s1", "name": "Paris VPN"})).startswith("به Paris VPN خوش آمدید")


@pytest.mark.asyncio
@pytest.mark.parametrize("store", [{"id": "s1"}, {"id": "s1", "name": None}, {"id": "s1", "name": "  "}])
async def test_welcome_without_a_name_is_neutral_not_the_platform_and_never_none(runner, store):
    text = await _welcome(runner, store)
    assert text.startswith(f"به {NEUTRAL_STORE_NAME} خوش آمدید")
    assert "None" not in text and "ملورین" not in text


async def _referral(runner, data, bot):
    shown = []

    async def api(ctx, method, path, **kw):
        return data

    async def tg(method, payload=None, **kw):
        return bot

    async def send(chat_id, text, **kw):
        shown.append(text)

    runner.api, runner.tg, runner.send = api, tg, send
    await runner.cmd_referral(_ctx(), "")
    return shown[0]


@pytest.mark.asyncio
async def test_referral_link_uses_this_bots_own_username(runner):
    text = await _referral(runner, {"referral_code": "AB12"}, {"username": "paris_bot"})
    assert "https://t.me/paris_bot?start=ref_AB12" in text


@pytest.mark.asyncio
async def test_referral_never_invents_a_bot_when_the_username_is_unknown(runner):
    text = await _referral(runner, {"referral_code": "AB12"}, {})
    assert "t.me" not in text and "MelorinBot" not in text
    assert "<code>AB12</code>" in text  # the code alone is still true and usable


def test_referral_text_without_link_or_code_just_omits_the_line():
    text = referral_text({"referred_count": 2}, None)
    assert "لینک اختصاصی" not in text and "کد دعوت" not in text and "<b>2</b>" in text
