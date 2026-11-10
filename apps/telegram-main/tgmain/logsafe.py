"""Log hygiene for the bots (T20/T40): never let a bot token reach stdout.

The bots are separate images and cannot import ``melorin.core``, so this is a
dependency-free twin of ``melorin.core.redact``. Use ``setup_bot_logging()`` instead of
``logging.basicConfig``.
"""

import logging
import os
import re

TOKEN_RE = re.compile(r"(?:bot)?\d{6,15}:[A-Za-z0-9_-]{20,}")
MASK = "bot<redacted>"


def scrub(text: str) -> str:
    return TOKEN_RE.sub(MASK, text)


class RedactTokens(logging.Filter):
    """httpx error text contains the request URL, i.e. the bot token. Redacts message, args, traceback and stack."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(str(record.msg))
        if record.args:
            args = record.args if isinstance(record.args, tuple) else (record.args,)
            record.args = tuple(scrub(a) if isinstance(a, str) else scrub(str(a)) if isinstance(a, BaseException) else a for a in args)
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = scrub(logging.Formatter().formatException(record.exc_info))
        if record.stack_info:
            record.stack_info = scrub(record.stack_info)
        return True


def setup_bot_logging(level: str | None = None) -> None:
    logging.basicConfig(level=level or os.getenv("LOG_LEVEL", "INFO"))
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactTokens) for f in handler.filters):
            handler.addFilter(RedactTokens())
    # httpx logs "HTTP Request: POST https://api.telegram.org/bot<token>/..." at INFO.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
