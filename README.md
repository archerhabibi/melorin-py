# Melorin

[فارسی](README.fa.md)

VPN sales and management platform: main store, reseller stores, Telegram bots, admin panel and a central API (FastAPI, PostgreSQL, Redis; React front ends). Modular Monolith. **Unreleased.**

## Quick start

Prerequisites: Docker with Compose v2 (production) or Python 3.12 + Node 22 + PostgreSQL + Redis (development).

Production (a fresh Ubuntu 22.04+/Debian 12+ server, as root; 4 GB RAM): one line, see docs/18 for flags (`install --yes`, `doctor`, `--external-proxy`).

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/get.sh)
```

Development / from a clone:

```bash
git clone https://github.com/archerhabibi/melorin-py.git && cd melorin-py
sudo bash melorin.sh install        # production install from a clone (docs/18)
# development
cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
alembic upgrade head && pytest -q
```

Full install, deployment, backup/restore and local development: [docs/18-OPERATIONS-DEPLOYMENT-DR.md](docs/18-OPERATIONS-DEPLOYMENT-DR.md). Database baseline: [docs/19-DATABASE-MIGRATIONS.md](docs/19-DATABASE-MIGRATIONS.md).

## Install notes

- Recommended server: 4 GB RAM (the compose memory budget is 3584 MiB). With an external reverse proxy use `EXTERNAL_PROXY=true` and bind to `127.0.0.1:18080`: `docker compose -f docker-compose.yml -f docker-compose.external.yml up -d --build`.
- Manual steps: `alembic upgrade head`, then the Admin bootstrap (create the first admin) and add panels / payment methods in the Admin panel; optional integrations (S3 backups, Google/Telegram login) are described in the docs below.

- Database: this release changed the Alembic baseline (new `refund_operations` table). A pre-release development database must be recreated from the baseline (`alembic upgrade head` on an empty DB).
- Refunds: gateway refunds run as a durable workflow (claim -> gateway call without locks -> ledger reversal); the worker's `refund_recovery_job` repairs interrupted ones, and providers without refund support (manual card) end in `manual_review`. Details: [docs/15-PAYMENTS-WALLET-FINANCE.md](docs/15-PAYMENTS-WALLET-FINANCE.md).
- Quality gate: `make guards` / `scripts/run_quality_gate.sh`. `npm audit` blocks runtime dependencies at `high` and dev tooling at `critical` (ADR-R2 in [docs/06](docs/06-ARCHITECTURE-DECISIONS.md)). Browser E2E (`e2e/`) is a blocking CI job.

## Documentation

All reference documents are bilingual (Persian first, then English). Start at [docs/00-DOCUMENTATION-INDEX.md](docs/00-DOCUMENTATION-INDEX.md).

- [Index / فهرست](docs/00-DOCUMENTATION-INDEX.md)
- [Product / محصول](docs/01-PRODUCT-OVERVIEW.md)
- [Architecture / معماری](docs/05-SYSTEM-ARCHITECTURE.md)
- [Admin UI / پنل ادمین](docs/09-ADMIN-UI-ARCHITECTURE.md)
- [API](docs/11-API-CONTRACTS.md)
- [Security / امنیت](docs/12-SECURITY-AUTHORIZATION.md)
- [Operations / عملیات](docs/18-OPERATIONS-DEPLOYMENT-DR.md)
- [Database / پایگاه داده](docs/19-DATABASE-MIGRATIONS.md)
- [Testing / تست](docs/20-TESTING-QUALITY-RELEASE.md)
- [Roadmap & debt / نقشه راه](docs/21-ROADMAP-TECHNICAL-DEBT.md)

`docs/STATUS.md` and `docs/API.md` are generated (`make docs`).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The previous long README is preserved in [docs/01-PRODUCT-OVERVIEW.md](docs/01-PRODUCT-OVERVIEW.md).
