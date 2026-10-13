"""Optional integrations (SMTP e-mail, S3 off-site backup) configured at runtime from the Admin panel.

Both are OFF by default so a fresh install needs neither. Secrets are stored Fernet-encrypted inside
``SystemSetting`` rows whose keys start with ``integration.``; those rows are never returned by the
generic ``/admin/settings`` endpoints and secrets are never written to the audit log.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import settings_store
from melorin.core.crypto import decrypt, encrypt

PREFIX = "integration."
EMAIL_KEY = PREFIX + "email"
BACKUP_S3_KEY = PREFIX + "backup_s3"
ADMIN_ACCESS_KEY = PREFIX + "admin_access"

EMAIL_DEFAULT: dict = {
    "enabled": False, "host": "", "port": 587, "username": "", "password_enc": None,
    "from_addr": "", "security": "starttls",  # starttls | ssl | none
}
BACKUP_S3_DEFAULT: dict = {
    "enabled": False, "endpoint": "", "region": "", "bucket": "", "prefix": "melorin",
    "access_key": "", "secret_key_enc": None,
}
ADMIN_ACCESS_DEFAULT: dict = {"enabled": False, "ips": []}  # OFF by default: no IP restriction on the admin API


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
        "enabled": bool(cfg["enabled"]), "host": cfg["host"], "port": cfg["port"], "username": cfg["username"],
        "from_addr": cfg["from_addr"], "security": cfg["security"], "password_set": bool(cfg.get("password_enc")),
    }


def public_backup_s3(cfg: dict) -> dict:
    return {
        "enabled": bool(cfg["enabled"]), "endpoint": cfg["endpoint"], "region": cfg["region"], "bucket": cfg["bucket"],
        "prefix": cfg["prefix"], "access_key": cfg["access_key"], "secret_key_set": bool(cfg.get("secret_key_enc")),
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
