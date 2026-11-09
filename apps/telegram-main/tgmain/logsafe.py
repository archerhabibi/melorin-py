"""Log hygiene for the Telegram bots (audit T20/T40).

``httpx.HTTPStatusError`` renders the full request URL, and the Bot API URL embeds the token
(``https://api.telegram.org/bot<id>:<secret>/getUpdates``). The filter below scrubs the message, its
arguments and the formatted traceback before any handler sees them.
"""

import logging
import re

TOKEN_RE = re.compile(r"bot\d{6,15}:[A-Za-z0-9_-]{20,}")
_BARE_TOKEN_RE = re.compile(r"\b\d{6,15}:[A-Za-z0-9_-]{30,}\b")
REDACTED = "bot<redacted>"


def redact(text: str) -> str:
    return _BARE_TOKEN_RE.sub("<redacted>", TOKEN_RE.sub(REDACTED, text))


class RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            args = record.args if isinstance(record.args, tuple) else (record.args,)
            record.args = tuple(redact(a) if isinstance(a, str) else redact(str(a)) if isinstance(a, BaseException) else a for a in args)
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def install(level: str = "INFO") -> None:
    """``logging.basicConfig`` + the redaction filter on every root handler."""
    logging.basicConfig(level=level)
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactTokens())
