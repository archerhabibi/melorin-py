"""Characterisation tests for ``Settings.validate_runtime_security``.

Phase 3.6 turned the validator into a table of rules. These tests pin the
observable contract (which field value is rejected, with which message, and in
which order) so the table cannot silently drift from the old if-chain.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from melorin.core.config import Settings

_S32 = "s" * 32


def _prod(**over):
    base = dict(
        env="production",
        encryption_key=Fernet.generate_key().decode(),
        cors_origins=["https://shop.example.com"],
        public_api_url="https://api.example.com",
        database_url="postgresql+asyncpg://melorin:Zx9-strong@db:5432/melorin",
        jwt_secret="j" * 40,
        bot_service_secret="b" * 40,
        metrics_token="m" * 40,
        health_token="h" * 40,
        backup_recipient_file="/run/secrets/age-recipients.txt",
        allow_mock_providers=False,
        redis_url="redis://redis:6379/0",
        require_redis_rate_limit=True,
    )
    base.update(over)
    return Settings(_env_file=None, **base)


def test_valid_production_settings_pass():
    assert _prod().env == "production"


def test_development_defaults_skip_every_rule():
    assert Settings(_env_file=None).env == "development"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"encryption_key": "not-a-fernet-key"}, "must be a valid Fernet key"),
        ({"encryption_key": ""}, "must be a valid Fernet key"),
        ({"cors_origins": []}, "absolute http(s) origins"),
        ({"cors_origins": ["shop.example.com"]}, "absolute http(s) origins"),
        ({"cors_origins": ["ftp://shop.example.com"]}, "absolute http(s) origins"),
        ({"cors_origins": ["*"]}, "absolute http(s) origins"),
        ({"cors_allow_methods": ["*"]}, "wildcard"),
        ({"cors_allow_headers": ["*"]}, "wildcard"),
        ({"public_api_url": ""}, "PUBLIC_API_URL"),
        ({"public_api_url": "http://api.example.com"}, "PUBLIC_API_URL"),
        ({"public_api_url": "https://"}, "PUBLIC_API_URL"),
        ({"database_url": "postgresql+asyncpg://melorin:melorin@db/melorin"}, "weak/default credential"),
        ({"database_url": "postgresql://u:change-me@db/melorin"}, "weak/default credential"),
        ({"jwt_secret": "dev-insecure-change-me"}, "JWT_SECRET"),
        ({"jwt_secret": "short"}, "JWT_SECRET"),
        ({"bot_service_secret": "dev-bot-secret"}, "BOT_SERVICE_SECRET"),
        ({"bot_service_secret": ""}, "BOT_SERVICE_SECRET"),
        ({"bot_service_secret": "short"}, "BOT_SERVICE_SECRET"),
        ({"main_bot_secret": "short"}, "MAIN_BOT_SECRET"),
        ({"main_bot_secret": "b" * 40}, "MAIN_BOT_SECRET"),  # equals the shared secret
        ({"main_bot_secret": _S32 + "1", "reseller_bot_secret": _S32 + "1"}, "MAIN_BOT_SECRET"),
        ({"metrics_token": "short"}, "METRICS_TOKEN"),
        ({"health_token": ""}, "METRICS_TOKEN"),
        ({"allow_mock_providers": True}, "MOCK_PROVIDERS"),
        ({"redis_url": None}, "Redis and coordinated rate limiting"),
        ({"require_redis_rate_limit": False}, "Redis and coordinated rate limiting"),
        ({"backup_recipient_file": ""}, "BACKUP_RECIPIENT_FILE"),
    ],
)
def test_each_production_rule_rejects_its_violation(override, message):
    with pytest.raises(ValidationError) as exc:
        _prod(**override)
    assert message in str(exc.value)


def test_distinct_per_runner_secrets_are_accepted():
    s = _prod(main_bot_secret="a" * 40, reseller_bot_secret="c" * 40)
    assert s.main_bot_secret != s.reseller_bot_secret


def test_staging_is_enforced_like_production():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        _prod(env="staging", jwt_secret="short")


def test_staging_enforces_the_transport_rules_too():
    # Outside development the transport rules apply to staging as well.
    with pytest.raises(ValidationError, match="PUBLIC_API_URL"):
        _prod(env="staging", public_api_url="http://api.example.com")


def test_rules_report_the_first_violation_in_declared_order():
    # Fernet before CORS before public URL before secrets: a config that breaks
    # several rules at once must fail on the earliest one.
    with pytest.raises(ValidationError) as exc:
        _prod(encryption_key="bad", cors_origins=[], public_api_url="", jwt_secret="x")
    assert "Fernet" in str(exc.value)
    with pytest.raises(ValidationError) as exc:
        _prod(cors_origins=[], public_api_url="", jwt_secret="x")
    assert "absolute http(s) origins" in str(exc.value)
    with pytest.raises(ValidationError) as exc:
        _prod(public_api_url="", jwt_secret="x")
    assert "PUBLIC_API_URL" in str(exc.value)
    with pytest.raises(ValidationError) as exc:
        _prod(jwt_secret="x", allow_mock_providers=True)
    assert "JWT_SECRET" in str(exc.value)
