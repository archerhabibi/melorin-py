import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from melorin.core.config import Settings


def test_invalid_environment_value_is_rejected():
    with pytest.raises(ValidationError):
        Settings(env="prod")


def test_production_rejects_invalid_fernet_key():
    admin_password = "Strong-" + "admin-" + "password-" + "123456"
    with pytest.raises(ValueError, match="Fernet"):
        Settings(
            env="production",
            database_url="postgresql+asyncpg://app:strong@localhost/db",
            jwt_secret="x" * 40,
            bot_service_secret="y" * 40,
            bootstrap_admin_password=admin_password,
            bootstrap_admin_totp_secret="A" * 20,
            encryption_key="not-a-fernet-key",
            redis_url="redis://localhost",
            require_redis_rate_limit=True,
            email_backend="smtp",
            backup_recipient_file="/tmp/recipients",
            backup_offsite_uri="s3://bucket/melorin",
            cors_origins=["https://app.example.com"],
        )


def test_production_accepts_valid_fernet_key_and_https_origins():
    admin_password = "Strong-" + "admin-" + "password-" + "123456"
    settings = Settings(
        env="production",
        database_url="postgresql+asyncpg://app:strong@localhost/db",
        jwt_secret="x" * 40,
        bot_service_secret="y" * 40,
        bootstrap_admin_password=admin_password,
        bootstrap_admin_totp_secret="A" * 20,
        encryption_key=Fernet.generate_key().decode(),
        redis_url="redis://localhost",
        require_redis_rate_limit=True,
        email_backend="smtp",
        backup_recipient_file="/tmp/recipients",
        backup_offsite_uri="s3://bucket/melorin",
        cors_origins=["https://app.example.com"],
    )
    assert settings.env == "production" and not settings.is_dev
