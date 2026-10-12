# I34: external integration smoke gate

Added `scripts/integration_smoke.sh` as the canonical runtime gate for
PostgreSQL/Alembic, Redis configuration, API import, optional Compose startup,
and explicitly configured provider smoke checks. It fails closed when required
service URLs are missing and never treats mocks as evidence for real external
integrations.

Run it in CI or staging with package-registry, Docker, PostgreSQL, Redis,
Telegram/payment sandbox, and panel credentials. This sandbox has no npm,
Docker, PostgreSQL, Redis, or provider network, so only the script and static
contracts were validated here.
