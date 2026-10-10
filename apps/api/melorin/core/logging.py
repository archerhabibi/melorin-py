import json
import logging
import re
import sys

from melorin.core.context import correlation_id

_SECRET = re.compile(r"(\d{9,10}:[A-Za-z0-9_-]{30,})|(Bearer\s+[A-Za-z0-9._-]+)|(\b\d{16}\b)")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = _SECRET.sub("***", record.getMessage())
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": msg,
            "correlation_id": correlation_id.get(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
