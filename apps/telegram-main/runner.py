"""Production Telegram long-poll runner (main store bot): a thin entry point over :mod:`tgmain.core`."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tgmain lives next to this file

from tgmain.core import *  # noqa: E402,F401,F403
from tgmain.core import TelegramRunner, log  # noqa: E402,F401
from tgmain.logsafe import setup_bot_logging  # noqa: E402


async def _idle_disabled() -> None:
    log.warning("MELORIN_TELEGRAM_TOKEN is empty: the main Telegram bot is disabled. Add the token to .env and restart to enable it.")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    import os

    setup_bot_logging()
    if not os.environ.get("MELORIN_TELEGRAM_TOKEN", "").strip():
        asyncio.run(_idle_disabled())  # log once and idle, instead of a getUpdates traceback loop
    else:
        asyncio.run(TelegramRunner().run())
