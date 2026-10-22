"""Reseller Telegram runner.

Same Core-authenticated transport as the main runner, bound to one reseller Store per bot. Customers get the full
storefront under the store's own name and texts; the owner additionally gets a management menu (/manage, /report,
/customers, /payments, /prices). Authorization is enforced by Core (403 for non-owners); this process never holds
infrastructure credentials or other stores' data.

Where the bots come from
------------------------
Normal operation is *Core-driven*: the supervisor asks Core which reseller bots should run
(``GET /api/v1/internal/reseller-bots``), starts one isolated runner per store, restarts a runner when its token
changes, stops it when the store is suspended / the bot is switched off / the token is removed, and reports each
bot's real connection state back to Core, which the admin screen shows. Adding or editing a reseller in the admin
needs no restart and no environment variable.

Legacy static modes still work for development: ``MELORIN_RESELLER_BOTS_JSON`` (several bots) or
``MELORIN_TELEGRAM_RESELLER_TOKEN`` + ``MELORIN_STORE_SLUG`` (one bot).
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# ``tgreseller`` lives next to this file; the tests load this file by path, so make the sibling package importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tgreseller.bot import CUSTOMER_COMMANDS, DEBT_LABEL, OWNER_BUTTON, OWNER_CACHE_SECONDS, OWNER_COMMANDS, OWNER_HELP, STORE_CACHE_SECONDS, TOKEN_RE, BotRevoked, RedactTokens, ResellerTelegramRunner, _module, esc, keyboard, log, money  # noqa: E402
from tgreseller.hosting import HEARTBEAT_SECONDS, Slot, Supervisor, _static_bots, heartbeat_loop  # noqa: E402

# Names the tests and the supervisor reach through this module.
__all__ = ["CUSTOMER_COMMANDS", "DEBT_LABEL", "OWNER_BUTTON", "OWNER_CACHE_SECONDS", "OWNER_COMMANDS", "OWNER_HELP", "STORE_CACHE_SECONDS", "TOKEN_RE", "BotRevoked", "RedactTokens", "ResellerTelegramRunner", "_module", "esc", "keyboard", "log", "money", "HEARTBEAT_SECONDS", "Slot", "Supervisor", "_static_bots", "heartbeat_loop"]


async def main() -> None:
    heartbeat = heartbeat_loop(os.getenv("MELORIN_HEARTBEAT_FILE"))
    bots = _static_bots()
    if bots is None:
        log.info("reseller bots are managed by Core (admin → نمایندگان)")
        await asyncio.gather(heartbeat, Supervisor().run())
    else:
        await asyncio.gather(heartbeat, *(bot.run() for bot in bots))


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactTokens())
    asyncio.run(main())
