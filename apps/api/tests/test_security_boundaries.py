import pytest
from melorin.core.config import Settings
from melorin.channels.telegram import TelegramChannel


def test_production_rejects_default_secrets():
    with pytest.raises(ValueError):
        Settings(
            env="production",
            database_url="postgresql+asyncpg://x:x@localhost/x",
            redis_url="redis://localhost",
            encryption_key="x",
            email_backend="smtp",
        )


def test_channel_rejects_unknown_channel():
    with pytest.raises(ValueError):
        TelegramChannel(token="x", core_base_url="http://core", channel="admin")
