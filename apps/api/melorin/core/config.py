"""Application settings. All tunables come from env (prefix MELORIN_) or DB SystemSetting."""

from collections.abc import Callable
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# --------------------------------------------------------------------------- #
# Runtime-security rules (Phase 3.6: table-driven instead of a 34-branch if-chain)
# Each rule is ``(is_violated, message)``; ``_enforce`` raises on the first hit.
# --------------------------------------------------------------------------- #
_Rule = tuple[Callable[["Settings"], bool], str]


def _bad_fernet_key(s: "Settings") -> bool:
    try:
        Fernet(s.encryption_key.encode())
    except (ValueError, TypeError):
        return True
    return False


def _is_http_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    return bool(parsed.scheme and parsed.netloc and parsed.scheme in {"http", "https"})


def _is_https_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(url and parsed.scheme == "https" and parsed.netloc)


def _weak_secret(value: str, *, minimum: int = 32, placeholders: frozenset[str] = frozenset()) -> bool:
    return value in placeholders or len(value) < minimum


def _runner_secrets_invalid(s: "Settings") -> bool:
    per_runner = [v for v in (s.main_bot_secret, s.reseller_bot_secret) if v]
    too_short = any(len(v) < 32 for v in per_runner)
    not_distinct = len({*per_runner, s.bot_service_secret}) != len(per_runner) + 1
    return too_short or not_distinct


# Every environment except development.
_NON_DEV_RULES: tuple[_Rule, ...] = (
    (_bad_fernet_key, "MELORIN_ENCRYPTION_KEY must be a valid Fernet key outside development"),
    (
        lambda s: not s.cors_origins or not all(_is_http_origin(o) for o in s.cors_origins),
        "MELORIN_CORS_ORIGINS must contain only absolute http(s) origins",
    ),
    (
        lambda s: "*" in {*s.cors_origins, *s.cors_allow_methods, *s.cors_allow_headers},
        "CORS wildcard origins, methods, and headers are not allowed outside development",
    ),
    (lambda s: not _is_https_url(s.public_api_url), "MELORIN_PUBLIC_API_URL must be an absolute HTTPS URL outside development"),
)

# staging + production. Bootstrap credentials are one-time inputs consumed by
# `melorin.cli bootstrap`; they are intentionally absent from .env afterwards and
# must not be required merely to restart an already-bootstrapped stack. SMTP and the S3
# off-site backup are optional (enabled later from Admin -> Settings -> Integrations);
# local backups are always encrypted, so the age recipient file stays mandatory.
_HOSTED_RULES: tuple[_Rule, ...] = (
    (
        lambda s: "change-me" in s.database_url or "melorin:melorin@" in s.database_url,
        "MELORIN_DATABASE_URL contains a weak/default credential",
    ),
    (
        lambda s: _weak_secret(s.jwt_secret, placeholders=frozenset({"dev-insecure-change-me"})),
        "MELORIN_JWT_SECRET must be a unique secret of at least 32 characters outside development",
    ),
    (
        lambda s: _weak_secret(s.bot_service_secret, placeholders=frozenset({"dev-bot-secret", ""})),
        "MELORIN_BOT_SERVICE_SECRET must be configured outside development",
    ),
    (
        _runner_secrets_invalid,
        "MELORIN_MAIN_BOT_SECRET / MELORIN_RESELLER_BOT_SECRET must be at least 32 characters and differ from each other"
        " and from MELORIN_BOT_SERVICE_SECRET",
    ),
    (
        lambda s: _weak_secret(s.metrics_token) or _weak_secret(s.health_token),
        "MELORIN_METRICS_TOKEN and MELORIN_HEALTH_TOKEN must be configured outside development",
    ),
    (lambda s: s.allow_mock_providers, "MELORIN_ALLOW_MOCK_PROVIDERS cannot be enabled outside development"),
    (
        lambda s: not s.redis_url or not s.require_redis_rate_limit,
        "Redis and coordinated rate limiting are required outside development",
    ),
    (
        lambda s: not s.backup_recipient_file,
        "MELORIN_BACKUP_RECIPIENT_FILE is required outside development (local backups are encrypted)",
    ),
)


def _enforce(settings: "Settings", rules: tuple[_Rule, ...]) -> None:
    for is_violated, message in rules:
        if is_violated(settings):
            raise ValueError(message)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MELORIN_", env_file=".env", extra="ignore")

    env: Literal["development", "staging", "production"] = "development"
    app_name: str = "Melorin Core"
    database_url: str = "sqlite+aiosqlite:///./var/melorin-dev.db"
    db_pool_size: int = 10
    redis_url: str | None = "redis://localhost:6379/0"

    jwt_secret: str = "dev-insecure-change-me"
    jwt_access_ttl_seconds: int = 900
    refresh_ttl_days: int = 30
    encryption_key: str = ""  # Fernet key (urlsafe base64, 32 bytes). REQUIRED outside development.

    bot_service_secret: str = "dev-bot-secret"  # shared secret between Core and bot runners
    # Optional least-privilege secrets (docs/16-Channel-Binding-Design.md): with these set, the main runner can only open
    # sessions in the main store and the reseller runner only in reseller stores. The shared secret above keeps working
    # for both ("any"); a hardened install gives each runner its own secret and stops handing out the shared one.
    main_bot_secret: str = ""
    reseller_bot_secret: str = ""
    metrics_token: str = ""
    health_token: str = ""
    main_bot_token: str = ""
    google_client_id: str = ""
    # Website login approved in the Telegram bot (docs/TELEGRAM-WEB-LOGIN.md)
    telegram_web_login_ttl_seconds: int = 180
    telegram_web_login_number_match: bool = True

    store_web_url: str = "http://localhost:3000"
    public_api_url: str = ""
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]
    cors_allow_methods: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    cors_allow_headers: list[str] = ["Accept", "Authorization", "Content-Type", "Idempotency-Key", "X-Bot-Secret", "X-Request-ID"]
    storage_dir: str = "./var/storage"
    max_upload_bytes: int = 5 * 1024 * 1024
    backup_dir: str = "./var/backups"
    backup_recipient_file: str = ""
    backup_offsite_uri: str = ""
    backup_retention_days: int = 30
    default_currency: str = "IRT"

    email_backend: str = "console"  # console | smtp
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@melorin.local"

    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_totp_secret: str | None = None
    # Numeric Telegram ID of the main admin (asked by the installer): admin alerts are delivered to it by the main bot.
    bootstrap_admin_telegram_id: str | None = None
    seed_demo_data: bool = False

    worker_poll_interval: float = 2.0
    allow_mock_providers: bool = False
    require_redis_rate_limit: bool = True
    # Phase 5.6: the API sends baseline security headers itself so an EXTERNAL_PROXY install (no Caddy/nginx of ours in front)
    # is protected too. Headers a proxy already set are never overwritten. HSTS is only sent on requests that arrived over HTTPS.
    security_headers_enabled: bool = True
    hsts_max_age: int = 31536000
    # Compose pins the reverse-proxy network to 172.28.0.0/16. Override this
    # with the exact proxy CIDR(s) in any external deployment.
    trusted_proxy_ips: list[str] = ["127.0.0.1", "::1", "172.28.0.0/16"]

    @model_validator(mode="after")
    def validate_runtime_security(self):
        # Fail closed on typos such as "prod" before any environment-specific
        # safeguard can be skipped (Literal validation handles env parsing).
        # The rules are data (see the tables above the class): the first
        # violated rule wins, in declared order.
        if self.env != "development":
            _enforce(self, _NON_DEV_RULES)
        if self.env in {"staging", "production"}:
            _enforce(self, _HOSTED_RULES)
        return self

    @property
    def is_dev(self) -> bool:
        return self.env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
