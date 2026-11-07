"""PG-10 in the bot: the tools screen shows only what Core says is available, never calls owner-only tools for a customer, and a write
needs a confirmation tap. The bot computes nothing itself."""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tgmain.errors import CoreError  # noqa: E402
from tgmain.handlers.tools import ToolsMixin  # noqa: E402
from tgmain.ui import b64  # noqa: E402

ACC = str(uuid.uuid4())
TOKEN = b64(ACC)


def T(tool, available=True, write=False):
    return {"tool": tool, "label": tool, "write": write, "available": available, "reason": None if available else "no"}


CUSTOMER = [T("usage"), T("devices"), T("devices_manage", write=True), T("rotate", write=True)]
OWNER = CUSTOMER + [T("presence"), T("suspend", write=True)]


class Bot(ToolsMixin):
    def __init__(self, matrix, *, devices=1, fail_status=None):
        self.matrix, self.devices, self.fail_status = matrix, devices, fail_status
        self.calls, self.screens, self.sent = [], [], []

    async def _acc_base(self, scope):
        return f"/api/v1/stores/s1/{'reseller/accounts' if scope == 'ow' else 'vpn-accounts'}"

    async def api(self, ctx, method, path, **kw):
        self.calls.append((method, path))
        if method == "POST" and self.fail_status:
            raise CoreError(self.fail_status, "پنل پشتیبانی نمی‌کند")
        if path.endswith("/tools"):
            return self.matrix
        if path.endswith("/usage"):
            return {"days": 30, "total_bytes": 2 * 2**30, "points": []}
        if path.endswith("/devices"):
            return {"count": self.devices, "items": [{"hwid": "h", "label": "Pixel", "platform": "android"}] * self.devices}
        if path.endswith("/presence"):
            return {"never_connected": True, "online_now": False, "online_at": None}
        return {}

    async def screen(self, ctx, text, rows=None):
        self.screens.append((text, rows or []))

    async def send(self, chat_id, text, rows=None, **kw):
        self.sent.append(text)


class Ctx:
    chat_id = 1


def run(coro):
    return asyncio.run(coro)


def buttons(bot):
    return [b for row in bot.screens[-1][1] for b in row]


def test_customer_screen_offers_rotate_and_devices_but_no_owner_tools():
    bot = Bot(CUSTOMER)
    run(bot.cb_tools_a(Ctx(), TOKEN))
    labels = [t for t, _ in buttons(bot)]
    assert any("لینک اشتراک جدید" in t for t in labels)
    assert any("ریست" in t for t in labels)
    assert not any("تعلیق" in t for t in labels)
    assert not any(p.endswith("/presence") for _, p in bot.calls)
    assert "Pixel" in bot.screens[-1][0]


def test_owner_screen_shows_last_seen_and_suspend_resume():
    bot = Bot(OWNER)
    run(bot.cb_tools_o(Ctx(), TOKEN))
    text = bot.screens[-1][0]
    assert "هنوز اتصالی ثبت نشده" in text
    labels = [t for t, _ in buttons(bot)]
    assert any("تعلیق" in t for t in labels) and any("فعال‌سازی" in t for t in labels)
    assert all(p.startswith("/api/v1/stores/s1/reseller/accounts/") for _, p in bot.calls)


def test_a_tool_the_panel_cannot_serve_is_not_offered():
    bot = Bot([T("usage"), T("devices"), T("rotate", available=False, write=True), T("devices_manage", available=False, write=True)])
    run(bot.cb_tools_a(Ctx(), TOKEN))
    labels = [t for t, _ in buttons(bot)]
    assert not any("لینک اشتراک جدید" in t for t in labels)
    assert not any("ریست" in t for t in labels)
    assert "برخی ابزارها" in bot.screens[-1][0]


def test_rotate_asks_first_and_only_the_confirm_writes():
    bot = Bot(CUSTOMER)
    run(bot.cb_tool_rotate_ask_a(Ctx(), TOKEN))
    assert not [c for c in bot.calls if c[0] == "POST"]
    assert any(cb.startswith("atrc:") for _, cb in buttons(bot))
    run(bot.cb_tool_rotate_a(Ctx(), TOKEN))
    posts = [c for c in bot.calls if c[0] == "POST"]
    assert posts == [("POST", f"/api/v1/stores/s1/vpn-accounts/{ACC}/tools/rotate-subscription")]
    assert any("لینک جدید" in s for s in bot.sent)


def test_a_core_refusal_is_shown_and_the_screen_still_comes_back():
    bot = Bot(CUSTOMER, fail_status=409)
    run(bot.cb_tool_devices_a(Ctx(), TOKEN))
    assert any("پشتیبانی نمی‌کند" in s for s in bot.sent)
    assert bot.screens  # the tools screen is re-rendered, the user is not left on a dead end


def test_every_callback_fits_telegrams_64_byte_limit():
    bot = Bot(OWNER)
    run(bot.cb_tools_o(Ctx(), TOKEN))
    for _, cb in buttons(bot):
        assert len(cb.encode()) <= 64
    run(bot.cb_tool_suspend_ask(Ctx(), TOKEN))
    for _, cb in buttons(bot):
        assert len(cb.encode()) <= 64
