# ARCHITECTURE-MAP (Phase 0)

Source: file inspection at `ee384d6` + `docs/STATUS.md` (generated; `gen_docs.py --check` = PASS at baseline). Modular monolith: FastAPI / PostgreSQL / Redis, two React SPAs, two Telegram bot runners.

## Runtime topology (`docker-compose.yml`)
postgres 16 · redis 7 · `migrate` (one-shot alembic) · `api` · `worker` (arq) · `backup` · `secrets_init` · `store_web` · `admin_web` · `telegram_main` · `telegram_reseller` · `caddy` (profile `local-proxy`) · `alertmanager` · `prometheus`.
External-proxy variant: `docker-compose.external.yml`. Images are digest-pinned (`scripts/pin_images.py`).

## Code units
| Unit | Path | Size | Role |
|---|---|---|---|
| Domain (pure rules) | `apps/api/melorin/domain` | 30 files / 2.8k LOC | pricing, ledger, commission, order state, netpolicy, webhook rules. Imports nothing of ours (import-linter enforced) |
| Kernel (ORM) | `apps/api/melorin/kernel` | 18 files / 1.7k | SQLAlchemy models (82 tables), `models/*.py` per area |
| Core (infra) | `apps/api/melorin/core` | 36 files / 3.3k | config, db/uow, security, crypto, ratelimit, redis, middleware, audit, health, metrics, tracing, storage, email |
| Feature modules | `apps/api/melorin/modules/*` | 279 files / 37.9k | admin 6.3k, panel_integrations 5.5k, panelops 4.8k, identity 3.6k, payments 3.3k, vpn_accounts 2.9k, reseller 2.8k, catalog 2.0k, orders 1.3k, loyalty 1.2k, reports 1.1k, eventcenter, referral, tickets, wallet, webhooks, broadcast, notifications |
| Channels | `apps/api/melorin/channels/telegram` | 8 files / 1.4k | Telegram web login / OIDC / bot API facade |
| Worker | `apps/api/melorin/worker` | 14 files / 1.7k | arq jobs (accounts, backup, identity, panels, payments, reports), retention, metrics server, runner, lock wrapper |
| Bots | `apps/telegram-main`, `apps/telegram-reseller` | 34 / 10 files | thin HTTP clients of the Core API |
| Web | `apps/store-web` (82 files, TS/React), `apps/admin-web` (222 files, TS/JSX) | | store + reseller console; admin panel |
| Shared JS | `packages/api-client` (OpenAPI-generated), `packages/web-kit` | | |
| E2E | `e2e/` (Playwright, mocked Core API) | 6 specs | |
| Ops | `scripts/` (51 files), `infra/`, `melorin.sh`, `get.sh`, `.github/workflows` (6) | | install, deploy, backup/restore drills, quality guards |

## External integrations (adapters)
- Payments: `modules/payments/adapters` (`zarinpal`, `manual_card`, registry/base/destination); bank-SMS ingestion and matching (`payments/bank_sms/*`); receipt OCR (`receipt_ocr.py`, `ocr_job.py`).
- VPN panels: `modules/panel_integrations/adapters` (`sanaei` legacy+v3, `pasarguard` users/nodes/admins/events/ops, `upstream_bot` via Telethon, `mock`).
- Outbound webhooks: `modules/webhooks`, `domain/webhook.py`, `domain/netpolicy.py` (SSRF / DNS pinning).
- Storage and backups: `core/storage.py`, `worker/jobs_backup.py`, `backup_main.py` (S3 optional).
- Auth providers: Google login (`modules/identity/google.py`), Telegram OIDC/login (`channels/telegram`).
- Observability: Prometheus, Alertmanager, optional OTLP (`core/otlp.py`).

## Data
Single Alembic baseline `0001_initial_baseline` (82 tables, 440 API operations / 392 paths). Money: double-entry ledger (`domain/ledger.py`, `kernel/models/wallet.py`) and a durable `refund_operations` workflow. Docs: docs/07, 14, 15, 19.

## Entry points
`melorin.app:app` (uvicorn) · `melorin.worker.arq_app.WorkerSettings` (arq) · `melorin.cli` (bootstrap) · `backup_main` · bot `runner.py` x2.
