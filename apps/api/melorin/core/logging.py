import json
import logging
import sys

from melorin.core.context import correlation_id
from melorin.core.redact import scrub


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = scrub(record.getMessage())
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": msg,
            "correlation_id": correlation_id.get(),
        }
        if record.exc_info:
            data["exc"] = scrub(self.formatException(record.exc_info))
        if record.stack_info:
            data["stack"] = scrub(self.formatStack(record.stack_info))
        return json.dumps(data, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    # httpx logs every request URL at INFO; for Telegram that URL carries the bot token.
    logging.getLogger("httpx").setLevel(max(logging.WARNING, root.level))
    logging.getLogger("httpcore").setLevel(max(logging.WARNING, root.level))
