"""Application settings. All tunables come from env (prefix MELORIN_) or DB SystemSetting."""
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    metrics_token: str = ""
    health_token: str = ""
    main_bot_token: str = ""
    google_client_id: str = ""

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
    seed_demo_data: bool = False

    worker_poll_interval: float = 2.0
    allow_mock_providers: bool = False
    require_redis_rate_limit: bool = True
    # Compose pins the reverse-proxy network to 172.28.0.0/16. Override this
    # with the exact proxy CIDR(s) in any external deployment.
    trusted_proxy_ips: list[str] = ["127.0.0.1", "::1", "172.28.0.0/16"]

    @model_validator(mode="after")
    def validate_runtime_security(self):
        # Fail closed on typos such as "prod" before any environment-specific
        # safeguard can be skipped. Literal validation handles env parsing.
        if self.env != "development":
            try:
                Fernet(self.encryption_key.encode())
            except (ValueError, TypeError) as exc:
                raise ValueError("MELORIN_ENCRYPTION_KEY must be a valid Fernet key outside development") from exc
            if not self.cors_origins or any(
                not (parsed := urlparse(origin)).scheme or not parsed.netloc or parsed.scheme not in {"http", "https"}
                for origin in self.cors_origins
            ):
                raise ValueError("MELORIN_CORS_ORIGINS must contain only absolute http(s) origins")
            if "*" in self.cors_origins or "*" in self.cors_allow_methods or "*" in self.cors_allow_headers:
                raise ValueError("CORS wildcard origins, methods, and headers are not allowed outside development")
            if not self.public_api_url or not (parsed_api := urlparse(self.public_api_url)).scheme or not parsed_api.netloc or parsed_api.scheme != "https":
                raise ValueError("MELORIN_PUBLIC_API_URL must be an absolute HTTPS URL outside development")
        if self.env in {"staging", "production"}:
            if "change-me" in self.database_url or "melorin:melorin@" in self.database_url:
                raise ValueError("MELORIN_DATABASE_URL contains a weak/default credential")
            # Bootstrap credentials are one-time inputs consumed by
            # `melorin.cli bootstrap`, not runtime production requirements.
            # They are intentionally removed from .env afterwards and must not be
            # required merely to restart an already-bootstrapped production stack.
            if self.jwt_secret == "dev-insecure-change-me" or len(self.jwt_secret) < 32:
                raise ValueError("MELORIN_JWT_SECRET must be a unique secret of at least 32 characters outside development")
            if self.bot_service_secret in {"dev-bot-secret", ""} or len(self.bot_service_secret) < 32:
                raise ValueError("MELORIN_BOT_SERVICE_SECRET must be configured outside development")
            if len(self.metrics_token) < 32 or len(self.health_token) < 32:
                raise ValueError("MELORIN_METRICS_TOKEN and MELORIN_HEALTH_TOKEN must be configured outside development")
            if not self.encryption_key:
                raise ValueError("MELORIN_ENCRYPTION_KEY is required outside development")
            if self.allow_mock_providers:
                raise ValueError("MELORIN_ALLOW_MOCK_PROVIDERS cannot be enabled outside development")
            if not self.redis_url or not self.require_redis_rate_limit:
                raise ValueError("Redis and coordinated rate limiting are required outside development")
            # SMTP and S3 off-site backup are optional (enabled later from the Admin panel).
            # Local backups are always encrypted, so the age recipient file stays mandatory.
            if not self.backup_recipient_file:
                raise ValueError("MELORIN_BACKUP_RECIPIENT_FILE is required outside development (local backups are encrypted)")
            # Off-site S3/rclone backup is optional. Local encrypted backups keep the
            # installation and daily operation working without an S3 account; admins
            # can enable and test the off-site copy from Admin -> Settings -> Integrations.
        return self

    @property
    def is_dev(self) -> bool:
        return self.env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
