"""Optional integrations (SMTP e-mail, S3 off-site backup) configured at runtime from the Admin panel.

Both are OFF by default so a fresh install needs neither. Secrets are stored Fernet-encrypted inside
``SystemSetting`` rows whose keys start with ``integration.``; those rows are never returned by the
generic ``/admin/settings`` endpoints and secrets are never written to the audit log.
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import settings_store
from melorin.core.config import get_settings
from melorin.core.crypto import decrypt, encrypt

PREFIX = "integration."
EMAIL_KEY = PREFIX + "email"
BACKUP_S3_KEY = PREFIX + "backup_s3"
ADMIN_ACCESS_KEY = PREFIX + "admin_access"
GOOGLE_KEY = PREFIX + "google_login"
TELEGRAM_KEY = PREFIX + "telegram_login"
RECEIPT_OCR_KEY = PREFIX + "receipt_ocr"

EMAIL_DEFAULT: dict = {
    "enabled": False,
    "host": "",
    "port": 587,
    "username": "",
    "password_enc": None,
    "from_addr": "",
    "security": "starttls",  # starttls | ssl | none
}
BACKUP_S3_DEFAULT: dict = {
    "enabled": False,
    "endpoint": "",
    "region": "",
    "bucket": "",
    "prefix": "melorin",
    "access_key": "",
    "secret_key_enc": None,
}
ADMIN_ACCESS_DEFAULT: dict = {"enabled": False, "ips": []}  # OFF by default: no IP restriction on the admin API
# Google Sign-In (ID-token flow). Only the public OAuth Client ID is needed - no client secret is stored.
GOOGLE_DEFAULT: dict = {"enabled": False, "client_id": "", "admin_login": True, "store_login": True}
GOOGLE_CLIENT_ID_RE = re.compile(r"^[0-9]{6,}-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$")
# Login with Telegram. Two independent methods share one master switch:
#   * bot approval  (device-authorization flow, docs/TELEGRAM-WEB-LOGIN.md) - needs only the store's bot;
#   * OIDC redirect (https://core.telegram.org/bots/telegram-login)       - needs the bot's Client ID + Client Secret
#     that @BotFather shows under "Login Widget". The secret is stored Fernet-encrypted and never returned.
# Admins never sign in through Telegram (they use password + TOTP), so there is no admin switch.
TELEGRAM_DEFAULT: dict = {
    "enabled": True,
    "store_login": True,
    "bot_login": True,
    "number_match": True,
    "ttl_seconds": 180,
    "oidc_login": False,
    "client_id": "",
    "client_secret_enc": None,
}
TELEGRAM_CLIENT_ID_RE = re.compile(r"^[0-9]{5,20}$")  # a bot's numeric ID (the part of the bot token before ':')
TELEGRAM_TTL_MIN, TELEGRAM_TTL_MAX = 60, 600
# Automatic reading of card-to-card receipt images. A panel-saved config wins; until the admin saves one the legacy
# ``MELORIN_RECEIPT_OCR_*`` environment values keep working. The API key is Fernet-encrypted and never returned.
RECEIPT_OCR_ENGINES = ("auto", "vision", "tesseract", "off")
RECEIPT_OCR_DEFAULT: dict = {
    "engine": "auto",
    "api_key_enc": None,
    "base_url": "https://api.anthropic.com",
    "model": "claude-haiku-5-5",
    "timeout_seconds": 25,
    "tesseract_lang": "fas+eng",
}
RECEIPT_OCR_TIMEOUT_MIN, RECEIPT_OCR_TIMEOUT_MAX = 5, 90


def is_integration_key(key: str) -> bool:
    return key.startswith(PREFIX)


async def _load(session: AsyncSession, key: str, default: dict) -> dict:
    stored = await settings_store.get(session, key)
    return {**default, **(stored if isinstance(stored, dict) else {})}


async def get_email(session: AsyncSession) -> dict:
    return await _load(session, EMAIL_KEY, EMAIL_DEFAULT)


async def get_admin_access(session: AsyncSession) -> dict:
    return await _load(session, ADMIN_ACCESS_KEY, ADMIN_ACCESS_DEFAULT)


async def get_backup_s3(session: AsyncSession) -> dict:
    return await _load(session, BACKUP_S3_KEY, BACKUP_S3_DEFAULT)


async def get_google(session: AsyncSession) -> dict:
    """Effective Google Sign-In config. A panel-saved config always wins; until the admin saves one, the legacy
    ``MELORIN_GOOGLE_CLIENT_ID`` environment value keeps working so existing installs do not break on upgrade."""
    stored = await settings_store.get(session, GOOGLE_KEY)
    if isinstance(stored, dict):
        return {**GOOGLE_DEFAULT, **stored, "source": "panel"}
    env_id = (get_settings().google_client_id or "").strip()
    return {**GOOGLE_DEFAULT, "enabled": bool(env_id), "client_id": env_id, "source": "env" if env_id else "none"}


async def get_telegram(session: AsyncSession) -> dict:
    """Effective Telegram login config. Until the admin saves one, behaviour is exactly what earlier versions did:
    bot-approval login on (timing/number-matching from the ``MELORIN_TELEGRAM_WEB_LOGIN_*`` env values), OIDC off."""
    stored = await settings_store.get(session, TELEGRAM_KEY)
    if isinstance(stored, dict):
        return {**TELEGRAM_DEFAULT, **stored, "source": "panel"}
    s = get_settings()
    return {
        **TELEGRAM_DEFAULT,
        "number_match": bool(s.telegram_web_login_number_match),
        "ttl_seconds": int(s.telegram_web_login_ttl_seconds),
        "source": "default",
    }


async def get_receipt_ocr(session: AsyncSession) -> dict:
    """Effective receipt-OCR config: the panel-saved one, else the environment values (``source`` says which)."""
    stored = await settings_store.get(session, RECEIPT_OCR_KEY)
    if isinstance(stored, dict):
        return {**RECEIPT_OCR_DEFAULT, **stored, "source": "panel"}
    return {**receipt_ocr_from_env(), "source": "env"}


def receipt_ocr_from_env() -> dict:
    s = get_settings()
    return {
        "engine": s.receipt_ocr_engine,
        "api_key_enc": encrypt(s.receipt_ocr_api_key) if s.receipt_ocr_api_key else None,
        "base_url": s.receipt_ocr_base_url,
        "model": s.receipt_ocr_model,
        "timeout_seconds": s.receipt_ocr_timeout_seconds,
        "tesseract_lang": s.receipt_ocr_tesseract_lang,
    }


def receipt_ocr_key(cfg: dict) -> str:
    return decrypt(cfg.get("api_key_enc")) or ""


def public_receipt_ocr(cfg: dict) -> dict:
    return {
        "engine": cfg["engine"],
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "timeout_seconds": cfg["timeout_seconds"],
        "tesseract_lang": cfg["tesseract_lang"],
        "api_key_set": bool(cfg.get("api_key_enc")),
        "source": cfg.get("source", "panel"),
    }


def telegram_ttl(cfg: dict) -> int:
    return max(TELEGRAM_TTL_MIN, min(TELEGRAM_TTL_MAX, int(cfg.get("ttl_seconds") or TELEGRAM_DEFAULT["ttl_seconds"])))


def telegram_bot_ready(cfg: dict) -> bool:
    return bool(cfg.get("enabled") and cfg.get("store_login") and cfg.get("bot_login"))


def telegram_oidc_ready(cfg: dict) -> bool:
    return bool(
        cfg.get("enabled") and cfg.get("store_login") and cfg.get("oidc_login") and cfg.get("client_id") and cfg.get("client_secret_enc")
    )


def telegram_client_secret(cfg: dict) -> str:
    return decrypt(cfg.get("client_secret_enc")) or ""


def public_telegram(cfg: dict) -> dict:
    """What the unauthenticated storefront may see: which buttons to draw. Never the Client ID or the secret."""
    return {"bot_login": telegram_bot_ready(cfg), "oidc_login": telegram_oidc_ready(cfg)}


def google_ready(cfg: dict) -> bool:
    return bool(cfg.get("enabled") and cfg.get("client_id"))


def public_google(cfg: dict) -> dict:
    """What the unauthenticated storefront/admin login pages may see (a Client ID is public by design)."""
    ready = google_ready(cfg)
    return {
        "enabled": ready,
        "client_id": cfg["client_id"] if ready else "",
        "admin_login": bool(cfg["admin_login"]),
        "store_login": bool(cfg["store_login"]),
    }


def email_ready(cfg: dict) -> bool:
    return bool(cfg.get("enabled") and cfg.get("host") and cfg.get("from_addr"))


def backup_s3_ready(cfg: dict) -> bool:
    return bool(cfg.get("enabled") and cfg.get("bucket") and cfg.get("access_key") and cfg.get("secret_key_enc"))


def email_password(cfg: dict) -> str:
    return decrypt(cfg.get("password_enc")) or ""


def s3_secret(cfg: dict) -> str:
    return decrypt(cfg.get("secret_key_enc")) or ""


def merge_secret(current_enc: str | None, new_plain: str | None) -> str | None:
    """None -> keep the stored secret, "" -> clear it, anything else -> replace it."""
    if new_plain is None:
        return current_enc
    return encrypt(new_plain) if new_plain != "" else None


async def save(session: AsyncSession, key: str, cfg: dict) -> None:
    await settings_store.set_value(session, key, cfg)


def public_email(cfg: dict) -> dict:
    return {
        "enabled": bool(cfg["enabled"]),
        "host": cfg["host"],
        "port": cfg["port"],
        "username": cfg["username"],
        "from_addr": cfg["from_addr"],
        "security": cfg["security"],
        "password_set": bool(cfg.get("password_enc")),
    }


def public_backup_s3(cfg: dict) -> dict:
    return {
        "enabled": bool(cfg["enabled"]),
        "endpoint": cfg["endpoint"],
        "region": cfg["region"],
        "bucket": cfg["bucket"],
        "prefix": cfg["prefix"],
        "access_key": cfg["access_key"],
        "secret_key_set": bool(cfg.get("secret_key_enc")),
    }


def rclone_env(cfg: dict) -> dict[str, str]:
    """Environment for ``rclone`` with an in-memory remote named ``melorins3`` (no config file on disk)."""
    env = {
        "RCLONE_CONFIG_MELORINS3_TYPE": "s3",
        "RCLONE_CONFIG_MELORINS3_PROVIDER": "Other",
        "RCLONE_CONFIG_MELORINS3_ACCESS_KEY_ID": cfg["access_key"],
        "RCLONE_CONFIG_MELORINS3_SECRET_ACCESS_KEY": s3_secret(cfg),
    }
    if cfg.get("endpoint"):
        env["RCLONE_CONFIG_MELORINS3_ENDPOINT"] = cfg["endpoint"]
    if cfg.get("region"):
        env["RCLONE_CONFIG_MELORINS3_REGION"] = cfg["region"]
    return env


def rclone_uri(cfg: dict) -> str:
    prefix = (cfg.get("prefix") or "").strip("/")
    return f"melorins3:{cfg['bucket']}" + (f"/{prefix}" if prefix else "")
