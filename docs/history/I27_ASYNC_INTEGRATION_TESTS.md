# I27: async and integration test depth

The API test toolchain now includes pinned `pytest-asyncio` and `pytest-cov`.
The quality gate can execute native async tests, and an executable regression
test covers the Redis rate-limit increment/expiry boundary.

Tests that require PostgreSQL, Redis, Docker, Telegram, payment gateways, or
VPN panels remain marked as integration work and must run in CI/staging with
real service dependencies.
