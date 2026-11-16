"""Docs/25 section 8.1: the main menu has an always-visible "link my accounts" button; the screen shows only what Core reports."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tgmain.handlers.identity import IdentityMixin  # noqa: E402
from tgmain.ui import LINK_BUTTON, MAIN_MENU, MENU  # noqa: E402


class Bot(IdentityMixin):
    def __init__(self, url="https://shop.example.com/h/abc"):
        self.url, self.screens, self.calls = url, [], []

    async def api(self, ctx, method, path, **kw):
        self.calls.append((method, path))
        return {
            "accounts": [{"id": "1"}, {"id": "2"}],
            "identities": [
                {"provider": "telegram", "label": "123456789"},
                {"provider": "google", "label": "a<b>@example.com"},
            ],
        }

    async def account_url(self, ctx):
        return self.url

    async def screen(self, ctx, text, rows):
        self.screens.append((text, rows))


def test_button_is_in_both_menus():
    assert [LINK_BUTTON] in MAIN_MENU
    assert any(cb == "menu:link" for row in MENU for _, cb in row)


def test_screen_lists_identities_escaped_and_offers_the_site_link():
    bot = Bot()
    asyncio.run(bot.cmd_link_accounts(None, ""))
    text, rows = bot.screens[0]
    assert bot.calls == [("GET", "/api/v1/identity/linked-accounts")]
    assert "123456789" in text and "a&lt;b&gt;@example.com" in text and "<b>@" not in text
    assert rows[0][0][1].startswith("https://")


def test_screen_without_a_usable_site_url_still_works():
    bot = Bot(url=None)
    asyncio.run(bot.cmd_link_accounts(None, ""))
    assert bot.screens[0][1] == [[("🏠 خانه", "menu:home")]]
