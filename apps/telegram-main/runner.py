"""Production Telegram long-poll runner (main store bot): a thin entry point over :mod:`tgmain.core`."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tgmain lives next to this file

from tgmain.core import *  # noqa: E402,F401,F403
from tgmain.core import TelegramRunner, log  # noqa: E402,F401
from tgmain.logsafe import setup_bot_logging  # noqa: E402


if __name__ == "__main__":
    setup_bot_logging()
    asyncio.run(TelegramRunner().run())
