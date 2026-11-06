"""The bot's club screen shows only what Core reports for THIS store and spends points only through Core, with a replay-safe key."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner import TelegramRunner  # noqa: E402
from tgmain.client import Ctx  # noqa: E402
from tgmain.errors import CoreError  # noqa: E402
from tgmain.ui import BOT_COMMANDS, HELP, loyalty_keyboard_rows, loyalty_text  # noqa: E402

CLUB = {
    "store_id": "s1",
    "enabled": True,
    "currency": "IRT",
    "balance": 1200,
    "lifetime_earned": 1500,
    "debt": 0,
    "tier": {"name": "نقره‌ای", "min_points": 500, "multiplier_bp": 11000},
    "next_tier": {"name": "طلایی", "min_points": 2000, "points_missing": 500},
    "program": {"first_order_bonus": 100},
    "rewards": [
        {"id": "r1", "name": "اعتبار ۵ هزار", "cost_points": 500, "value": 5000, "available": True, "blocked_reason": None},
        {
            "id": "r2",
            "name": "اعتبار بزرگ",
            "cost_points": 9000,
            "value": 90000,
            "available": False,
            "blocked_reason": "LOYALTY_NOT_ENOUGH_POINTS",
        },
    ],
    "history": [{"id": "t1", "kind": "order_earn", "amount": 120}],
}


def test_text_comes_from_core_numbers_and_explains_what_is_blocked():
    text = loyalty_text(CLUB)
    assert "<b>1,200</b>" in text
    assert "نقره‌ای" in text and "1.1×" in text
    assert "«طلایی»" in text and "<b>500</b>" in text
    assert "امتیاز کافی نیست" in text
    assert "5,000 تومان" in text
    assert "+120" in text


def test_store_without_a_club_says_so():
    text = loyalty_text({"store_id": "s1", "enabled": False})
    assert "ندارد" in text
    assert "امتیاز شما" not in text


def test_debt_is_explained_and_top_tier_is_named():
    text = loyalty_text({**CLUB, "debt": 80, "next_tier": None})
    assert "80" in text and "بازگشت وجه" in text
    assert "بالاترین سطح" in text


def test_only_rewards_core_marks_available_get_a_button():
    rows = loyalty_keyboard_rows(CLUB)
    assert rows[0] == [("🎁 اعتبار ۵ هزار · 500", "loy:r:r1")]
    assert all("r2" not in cb for row in rows for _, cb in row)
    assert rows[-1] == [("🏠 خانه", "menu:home")]
    assert all(len(cb.encode()) <= 64 for row in rows for _, cb in row)


def test_command_is_listed_in_help_and_menu():
    assert "/club" in HELP
    assert any(c == "club" for c, _ in BOT_COMMANDS)


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("MELORIN_CORE_URL", "http://core.invalid")
    monkeypatch.setenv("MELORIN_BOT_SERVICE_SECRET", "x" * 32)
    r = TelegramRunner(token="123:abc", offset_file=tmp_path / "offset.json")
    r.shown, r.calls = [], []

    async def store_info():
        return {"id": "s1"}

    async def screen(ctx, text, rows=None):
        r.shown.append((text, rows))

    r.store_info, r.screen = store_info, screen
    return r


def _ctx():
    return Ctx(777, {"id": 777}, {"access_token": "t"}, 5, callback_id="cb9", message_id=3)


def test_club_is_wired_into_commands_callbacks_and_menu(runner):
    assert runner.commands["/club"] == runner.cmd_club
    assert runner.callbacks["loy"] == runner.cb_loyalty


@pytest.mark.asyncio
async def test_command_asks_core_for_this_stores_club(runner):
    async def api(ctx, method, path, **kw):
        runner.calls.append((method, path, kw))
        return CLUB

    runner.api = api
    await runner.cmd_club(_ctx(), "")
    assert runner.calls == [("GET", "/api/v1/stores/s1/loyalty", {})]
    assert "باشگاه مشتریان" in runner.shown[0][0]


@pytest.mark.asyncio
async def test_redeem_sends_a_replay_safe_key_and_refreshes_the_club(runner):
    async def api(ctx, method, path, **kw):
        runner.calls.append((method, path, kw))
        return {"id": "x", "replayed": False} if method == "POST" else CLUB

    runner.api = api
    await runner.cb_loyalty(_ctx(), "r:r1")
    post = runner.calls[0]
    assert post[0] == "POST" and post[1] == "/api/v1/stores/s1/loyalty/rewards/r1/redeem"
    assert post[2]["headers"] == {"Idempotency-Key": "tg-cb9-loyalty"}
    assert runner.calls[1][0] == "GET"
    assert runner.shown[0][0].startswith("✅ پاداش شما به کیف پول اضافه شد.")


@pytest.mark.asyncio
async def test_core_refusal_is_shown_not_raised(runner):
    async def api(ctx, method, path, **kw):
        if method == "POST":
            raise CoreError(400, "سقف دریافت این جایزه برای شما پر شده است.", "LOYALTY_REWARD_LIMIT")
        return CLUB

    runner.api = api
    await runner.cb_loyalty(_ctx(), "r:r1")
    assert "سقف دریافت" in runner.shown[0][0]


@pytest.mark.asyncio
async def test_unknown_callback_payload_just_reopens_the_club(runner):
    async def api(ctx, method, path, **kw):
        runner.calls.append(method)
        return CLUB

    runner.api = api
    await runner.cb_loyalty(_ctx(), "zzz")
    assert runner.calls == ["GET"]
