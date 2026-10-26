"""The wallet screen of the bot shows the user's numeric Telegram ID."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner import TelegramRunner  # noqa: E402
from tgmain.client import Ctx  # noqa: E402


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("MELORIN_CORE_URL", "http://core.invalid")
    monkeypatch.setenv("MELORIN_BOT_SERVICE_SECRET", "x" * 32)
    return TelegramRunner(token="123:abc", offset_file=tmp_path / "offset.json")


async def _show(runner, wallet):
    shown = []

    async def store_info():
        return {"id": "s1"}

    async def api(ctx, method, path, **kw):
        return wallet if path.endswith("/wallet") else []

    async def screen(ctx, text, rows=None):
        shown.append(text)

    runner.store_info, runner.api, runner.screen = store_info, api, screen
    await runner.cmd_wallet(Ctx(777, {"id": 777}, {"access_token": "t"}, 1), "")
    return shown[0]


@pytest.mark.asyncio
async def test_shows_the_id_that_core_reports(runner):
    text = await _show(
        runner, {"balance": 1000, "currency": "IRT", "telegram_id": "123456789"}
    )
    assert "<code>123456789</code>" in text


@pytest.mark.asyncio
async def test_falls_back_to_the_chat_user_id(runner):
    text = await _show(
        runner, {"balance": 1000, "currency": "IRT", "telegram_id": None}
    )
    assert "<code>777</code>" in text
