"""One place that knows what a secret looks like in a log line (T20/T40).

Telegram embeds the bot token in the request URL (``/bot<id>:<secret>/method``), so any
``httpx.HTTPStatusError`` text or traceback would leak it. ``scrub`` is the single regex
used by Core's JSON logger; the bots carry a dependency-free twin in ``tgmain.logsafe``
(a contract test keeps the two patterns identical).
"""

import re

TELEGRAM_TOKEN_RE = re.compile(r"(?:bot)?\d{6,15}:[A-Za-z0-9_-]{20,}")
SECRET_RE = re.compile(
    r"(?:bot)?\d{6,15}:[A-Za-z0-9_-]{20,}|(Bearer\s+[A-Za-z0-9._-]+)|(\b\d{16}\b)"
)


def scrub(text: str) -> str:
    return SECRET_RE.sub("***", text)
