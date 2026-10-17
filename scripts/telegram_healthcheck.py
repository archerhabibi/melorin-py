"""Container healthcheck for Telegram runners.

* Main runner: a configured token is not enough, ask Telegram getMe with a short timeout.
* Reseller supervisor (``MELORIN_HEARTBEAT_FILE``): it may legitimately host zero bots, so there is no single token to
  ask about. It touches a heartbeat file every few seconds; a stale file means the process is stuck or dead.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HEARTBEAT_MAX_AGE = 90


def heartbeat_ok(path: str) -> bool:
    try:
        return time.time() - float(open(path).read().strip()) < HEARTBEAT_MAX_AGE
    except (OSError, ValueError):
        return False


def main() -> int:
    heartbeat = os.environ.get("MELORIN_HEARTBEAT_FILE", "").strip()
    if heartbeat:
        return 0 if heartbeat_ok(heartbeat) else 1
    token = os.environ.get("MELORIN_TELEGRAM_TOKEN", "").strip()
    if not token:
        return 1
    try:
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/getMe",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.load(response)
        return 0 if body.get("ok") and body.get("result", {}).get("is_bot") else 1
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
