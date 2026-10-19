"""SMTP and off-site S3 backups are optional production integrations."""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from melorin.core import config as config_mod
from melorin.core import crypto, db, integrations, settings_store
from melorin.core import email as email_mod
from melorin.core.config import Settings
from melorin.core.errors import AppError
from melorin.modules import system  # noqa: F401  (registers models)
from melorin.modules.system.models import SystemSetting


def _reset_caches():
    config_mod.get_settings.cache_clear()
    crypto._fernet.cache_clear()


def _prod(**kw):
    base = dict(
        env="production",
        database_url="postgresql+asyncpg://app:strong@localhost/db",
        jwt_secret="x" * 40,
        bot_service_secret="y" * 40,
        bootstrap_admin_password="Strong-admin-password-123456",  # pragma: allowlist secret
        encryption_key=Fernet.generate_key().decode(),
        bootstrap_admin_totp_secret="A" * 20,
        redis_url="redis://localhost",
        require_redis_rate_limit=True,
        metrics_token="m" * 40,
        health_token="h" * 40,
        public_api_url="https://shop.example.com:9443",
        cors_origins=["https://shop.example.com:9443"],
        backup_recipient_file="/run/melorin-backup/recipients.txt",
        backup_offsite_uri="s3://bucket/melorin",
    )
    base.update(kw)
    return Settings(**base)


def test_production_starts_without_smtp_or_s3():
    s = _prod(email_backend="console", backup_offsite_uri="")
    assert s.env == "production" and not s.backup_offsite_uri and s.email_backend == "console"


def test_production_still_requires_the_local_backup_recipient():
    with pytest.raises(ValueError, match="BACKUP_RECIPIENT"):
        _prod(backup_recipient_file="")


def test_merge_secret_semantics(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("MELORIN_ENCRYPTION_KEY", key)
    _reset_caches()
    try:
        enc = integrations.merge_secret(None, "s3cret")
        assert enc and "s3cret" not in enc and crypto.decrypt(enc) == "s3cret"
        assert integrations.merge_secret(enc, None) == enc  # keep
        assert integrations.merge_secret(enc, "") is None  # clear
    finally:
        _reset_caches()


def test_public_views_never_contain_secrets():
    em = {**integrations.EMAIL_DEFAULT, "password_enc": "gAAAA-secret"}
    s3 = {**integrations.BACKUP_S3_DEFAULT, "secret_key_enc": "gAAAA-secret"}
    assert "password_enc" not in integrations.public_email(em) and integrations.public_email(em)["password_set"] is True
    assert "secret_key_enc" not in integrations.public_backup_s3(s3) and integrations.public_backup_s3(s3)["secret_key_set"] is True


def test_rclone_uri_and_env():
    cfg = {
        **integrations.BACKUP_S3_DEFAULT,
        "bucket": "bk",
        "prefix": "/melorin/",
        "access_key": "AK",
        "endpoint": "https://s3.example.com",
    }
    assert integrations.rclone_uri(cfg) == "melorins3:bk/melorin"
    env = integrations.rclone_env({**cfg, "secret_key_enc": None})
    assert env["RCLONE_CONFIG_MELORINS3_ENDPOINT"] == "https://s3.example.com" and env["RCLONE_CONFIG_MELORINS3_TYPE"] == "s3"


@pytest.fixture
async def prod_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MELORIN_ENV", "development")  # real DB, but we flip is_dev per test below
    _reset_caches()
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(SystemSetting.__table__.create)
    yield
    await db.engine().dispose()
    _reset_caches()


class _Prod:
    is_dev = False
    email_backend = "console"
    smtp_host = ""


async def test_email_unavailable_in_production_until_enabled(prod_db, monkeypatch):
    monkeypatch.setattr(email_mod, "get_settings", lambda: _Prod())
    assert await email_mod.email_available() is False
    with pytest.raises(AppError) as err:
        await email_mod.send_email("a@b.co", "s", "b")
    assert err.value.code == "EMAIL_DISABLED" and err.value.status == 503

    sent = {}
    monkeypatch.setattr(email_mod, "_smtp_send", lambda cfg, to, subj, body: sent.update(cfg=cfg, to=to))
    async with db.session_factory()() as s:
        await integrations.save(
            s,
            integrations.EMAIL_KEY,
            {
                **integrations.EMAIL_DEFAULT,
                "enabled": True,
                "host": "smtp.x.io",
                "from_addr": "no-reply@x.io",
                "password_enc": crypto.encrypt("pw"),
            },
        )
        await s.commit()
    assert await email_mod.email_available() is True
    await email_mod.send_email("user@x.io", "s", "b")
    assert sent["to"] == "user@x.io" and sent["cfg"]["host"] == "smtp.x.io" and sent["cfg"]["password"] == "pw"


async def test_integration_rows_are_hidden_from_generic_settings(prod_db):
    async with db.session_factory()() as s:
        await integrations.save(s, integrations.BACKUP_S3_KEY, {**integrations.BACKUP_S3_DEFAULT, "secret_key_enc": "enc"})
        await settings_store.set_value(s, "test.enabled", False)
        await s.commit()
        out = await settings_store.all_settings(s)
        assert not any(k.startswith("integration.") for k in out) and out["test.enabled"] is False
        assert await s.scalar(select(SystemSetting.id).where(SystemSetting.key == integrations.BACKUP_S3_KEY))
