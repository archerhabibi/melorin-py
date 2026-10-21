"""Read-only diagnostics behind ``POST /integrations/telegram/test``.

Each check is a small function returning one result ``{"key", "status" (ok|warn|fail), "message"}``;
``run_diagnostics`` assembles them in a fixed order. Messages are shown to the admin verbatim.
"""

import httpx

from melorin.channels.telegram import oidc as telegram_oidc
from melorin.core import integrations
from melorin.core.config import get_settings


def _check(key: str, status: str, message: str) -> dict:
    return {"key": key, "status": status, "message": message}


def check_switches(cfg: dict) -> list[dict]:
    if not cfg["enabled"]:
        return [_check("enabled", "warn", "کلید اصلی «ورود با تلگرام» خاموش است؛ دکمه‌ای در فروشگاه نمایش داده نمی‌شود.")]
    if not cfg["store_login"]:
        return [_check("store_login", "warn", "«ورود مشتریان (فروشگاه)» خاموش است؛ دکمه‌ای در فروشگاه نمایش داده نمی‌شود.")]
    return []


def check_site_url(main_store) -> dict:
    origin = telegram_oidc.callback_origin(main_store)
    host = origin.split("://", 1)[1]
    if not origin.startswith("https://") or host.split(":")[0] in ("localhost", "127.0.0.1"):
        return _check(
            "site_url",
            "fail" if not get_settings().is_dev else "warn",
            f"آدرس فروشگاه ({origin}) https عمومی نیست. تلگرام فقط به آدرس‌های https ثبت‌شده برمی‌گرداند؛ MELORIN_STORE_WEB_URL را در .env اصلاح کنید.",
        )
    return _check("site_url", "ok", f"آدرس بازگشت: {telegram_oidc.redirect_uri(origin)} (باید در Allowed URLs ثبت شده باشد).")


async def check_discovery(c: httpx.AsyncClient) -> dict:
    try:
        doc = (await c.get(telegram_oidc.DISCOVERY_URL)).json()
    except (httpx.HTTPError, ValueError) as exc:
        return _check(
            "discovery",
            "fail",
            f"سرور به oauth.telegram.org وصل نشد ({type(exc).__name__}). دسترسی خروجی HTTPS/DNS/فایروال را بررسی کنید.",
        )
    ok = doc.get("issuer") == telegram_oidc.ISSUER
    return _check(
        "discovery", "ok" if ok else "fail", "سرور به oauth.telegram.org دسترسی دارد." if ok else "پاسخ Discovery تلگرام غیرمنتظره بود."
    )


async def check_jwks(c: httpx.AsyncClient) -> dict:
    try:
        keys = (await c.get(telegram_oidc.JWKS_URL)).json().get("keys", [])
    except (httpx.HTTPError, ValueError) as exc:
        return _check("jwks", "fail", f"دریافت کلیدهای امضا ناموفق بود ({type(exc).__name__}).")
    return _check(
        "jwks", "ok" if keys else "fail", f"{len(keys)} کلید امضا از تلگرام دریافت شد." if keys else "کلید امضایی از تلگرام دریافت نشد."
    )


def check_client_id(cfg: dict, token: str) -> dict:
    cid = cfg["client_id"]
    if not cid:
        return _check("client_id", "fail", "Client ID ذخیره نشده است.")
    bot_id = telegram_oidc.bot_id_of(token)
    if bot_id and bot_id != cid:
        return _check(
            "client_id",
            "warn",
            f"Client ID با شناسهٔ ربات اصلی ({bot_id}) یکی نیست. اگر عمداً از ربات دیگری استفاده می‌کنید مشکلی نیست.",
        )
    return _check("client_id", "ok", "Client ID با ربات اصلی هم‌خوان است." if bot_id else "Client ID ذخیره شده است.")


async def check_credentials(c: httpx.AsyncClient, cfg: dict) -> dict:
    """Posts a deliberately invalid authorization code: the *kind* of rejection tells whether the Client ID/Secret are accepted."""
    cid = cfg["client_id"]
    if not cfg.get("client_secret_enc") or not cid:
        return _check("credentials", "fail", "Client Secret ذخیره نشده است.")
    try:
        r = await c.post(
            telegram_oidc.TOKEN_URL,
            auth=(cid, integrations.telegram_client_secret(cfg)),
            data={
                "grant_type": "authorization_code",
                "code": "melorin-connectivity-check",
                "client_id": cid,
                "redirect_uri": telegram_oidc.redirect_uri(telegram_oidc.callback_origin(None)),
                "code_verifier": "x" * 43,
            },
        )
        err = telegram_oidc._oauth_error(r)  # parses the body: a malformed one is a "could not check", not a crash
    except (httpx.HTTPError, ValueError) as exc:
        return _check("credentials", "warn", f"بررسی اعتبارنامه انجام نشد ({type(exc).__name__}).")
    if r.status_code == 401 or err == "invalid_client":
        return _check("credentials", "fail", "تلگرام Client ID/Secret را نپذیرفت. هر دو را دوباره از BotFather کپی کنید.")
    if r.status_code >= 500:
        return _check("credentials", "warn", "سرور تلگرام خطا داد؛ بررسی اعتبارنامه انجام نشد. کمی بعد دوباره تست کنید.")
    return _check("credentials", "ok", "تلگرام اعتبارنامه را رد نکرد (درستی نهایی با یک ورود واقعی مشخص می‌شود).")


async def check_bot(c: httpx.AsyncClient, token: str, username: str) -> dict:
    if not token:
        return _check("bot", "fail", "توکن ربات اصلی تنظیم نشده است.")
    try:
        r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
        me = (r.json() or {}).get("result") or {}
    except (httpx.HTTPError, ValueError) as exc:
        return _check("bot", "fail", f"سرور به api.telegram.org وصل نشد ({type(exc).__name__}).")
    real = me.get("username")
    if r.status_code != 200 or not me:
        return _check("bot", "fail", "تلگرام توکن ربات اصلی را نپذیرفت (توکن ابطال یا اشتباه است).")
    if not username:
        return _check(
            "bot",
            "fail",
            f"نام کاربری ربات روی فروشگاه ثبت نشده است (ربات واقعی: @{real}). بدون آن لینک ورود ساخته نمی‌شود؛ در همین صفحه، بخش «ربات اصلی فروشگاه»، دکمهٔ «تشخیص خودکار» را بزنید.",
        )
    if (real or "").lower() != username.lower():
        return _check("bot", "warn", f"نام کاربری ربات در فروشگاه (@{username}) با ربات واقعی (@{real}) یکی نیست.")
    return _check("bot", "ok", f"ربات @{real} در دسترس است.")


async def run_diagnostics(cfg: dict, token: str, username: str, main_store) -> list[dict]:
    """All checks for the SAVED config, in display order. ``main_store`` is the main ``Store`` row (or None)."""
    checks = check_switches(cfg)
    if cfg["oidc_login"]:
        checks.append(check_site_url(main_store))
    async with httpx.AsyncClient(timeout=10) as c:
        if cfg["oidc_login"]:
            checks.append(await check_discovery(c))
            checks.append(await check_jwks(c))
            checks.append(check_client_id(cfg, token))
            checks.append(await check_credentials(c, cfg))
        if cfg["bot_login"]:
            checks.append(await check_bot(c, token, username))
    return checks or [_check("none", "warn", "هیچ روشی برای تست فعال نیست.")]
