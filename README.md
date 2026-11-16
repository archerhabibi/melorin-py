# Melorin

[فارسی](README.fa.md)

VPN sales and management platform: main store, reseller stores, Telegram bots, admin panel and a central API (FastAPI, PostgreSQL, Redis; React front ends). Modular Monolith. **Unreleased.**

## Quick start

Prerequisites: Docker with Compose v2 (production) or Python 3.12 + Node 22 + PostgreSQL + Redis (development).

```bash
git clone https://github.com/archerhabibi/melorin-py.git && cd melorin-py
sudo bash melorin.sh install        # production install (docs/18)
# development
cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
alembic upgrade head && pytest -q
```

Full install, deployment, backup/restore and local development: [docs/18-OPERATIONS-DEPLOYMENT-DR.md](docs/18-OPERATIONS-DEPLOYMENT-DR.md). Database baseline: [docs/19-DATABASE-MIGRATIONS.md](docs/19-DATABASE-MIGRATIONS.md).

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
