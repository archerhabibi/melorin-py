import json
import logging
import sys

from melorin.core.context import correlation_id, trace_id
from melorin.core.redact import scrub

redact = scrub  # back-compat name (audit T20 tests and callers import it from here)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = scrub(record.getMessage())
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": msg,
            "correlation_id": correlation_id.get(),
            "trace_id": trace_id.get(),
        }
        if record.exc_info:
            data["exc"] = scrub(self.formatException(record.exc_info))
        if record.stack_info:
            data["stack"] = scrub(self.formatStack(record.stack_info))
        return json.dumps(data, ensure_ascii=False)


class _QuietHeartbeat(logging.Filter):
    """arq writes two INFO lines per run; ``poll_tick`` runs every 2 s (~30k lines per 6 h of pure noise). Drop the success
    lines of that one job; a failure ("!" marker / exception) and every other job stay visible (audit V-026)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno > logging.INFO or record.exc_info:
            return True
        msg = record.getMessage()
        return not ("poll_tick" in msg and "!" not in msg)


def quiet_worker_heartbeat() -> None:
    lg = logging.getLogger("arq.worker")
    if not any(isinstance(f, _QuietHeartbeat) for f in lg.filters):
        lg.addFilter(_QuietHeartbeat())


def setup_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    # httpx logs every request URL at INFO; for Telegram that URL carries the bot token.
    logging.getLogger("httpx").setLevel(max(logging.WARNING, root.level))
    logging.getLogger("httpcore").setLevel(max(logging.WARNING, root.level))
    quiet_worker_heartbeat()
