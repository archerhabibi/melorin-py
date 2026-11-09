import json
import logging
import sys

from melorin.core.logging import JsonFormatter, redact

TOKEN = "123456789:AAH_abcdefghijklmnopqrstuvwxyz012345"


def test_redact_scrubs_bot_token_in_url():
    assert TOKEN not in redact(f"https://api.telegram.org/bot{TOKEN}/getUpdates")


def test_traceback_is_redacted():
    try:
        raise RuntimeError(f"429 for url https://api.telegram.org/bot{TOKEN}/getUpdates")
    except RuntimeError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "cycle failed", None, sys.exc_info())
    out = json.loads(JsonFormatter().format(record))
    assert TOKEN not in out["exc"]
    assert TOKEN not in json.dumps(out)
