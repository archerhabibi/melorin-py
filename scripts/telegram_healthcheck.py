"""Container healthcheck for Telegram runners.

A configured token is not enough: ask Telegram getMe with a short timeout.
"""
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
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
