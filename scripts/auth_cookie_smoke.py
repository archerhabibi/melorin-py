"""Live refresh-cookie smoke check. Requires an already authenticated browser cookie jar.

Usage: BASE_URL=... COOKIE_JAR=... python scripts/auth_cookie_smoke.py
"""
import os
import sys
from http.cookiejar import MozillaCookieJar
from urllib.parse import urljoin
import urllib.request


def main() -> int:
    base = os.environ.get("BASE_URL", "").rstrip("/")
    jar_path = os.environ.get("COOKIE_JAR", "")
    if not base or not jar_path:
        print("BASE_URL and COOKIE_JAR are required", file=sys.stderr)
        return 2
    jar = MozillaCookieJar(jar_path)
    jar.load(ignore_discard=True, ignore_expires=True)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(urljoin(base + "/", "api/v1/auth/refresh"), data=b"{}", method="POST", headers={"Content-Type": "application/json", "Origin": base})
    try:
        with opener.open(req, timeout=10) as response:
            if response.status != 200:
                return 1
            if not any(c.name == "melorin_refresh" and c.has_nonstandard_attr("HttpOnly") for c in jar):
                print("refresh cookie is not HttpOnly", file=sys.stderr)
                return 1
            print("refresh cookie smoke passed")
            return 0
    except OSError as exc:
        print(f"refresh cookie smoke failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
