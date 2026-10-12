# Melorin

Production-oriented modular monolith for a multi-store VPN platform. The implementation follows the supplied SRS and documentation pack.

> فارسی: [README.fa.md](README.fa.md)

## Install on a server

**Requirements:** an Ubuntu server (the installer uses `apt`) with root access, two domain names (store and admin)
pointing at the server, and **ports 80 and 443 free** (Caddy obtains the TLS certificates automatically).

```bash
curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/scripts/install_server.sh -o install.sh
DOMAIN=shop.example.com ADMIN_DOMAIN=admin.example.com ADMIN_EMAIL=you@example.com bash install.sh
```

If the repository is private, copy `scripts/install_server.sh` to the server and set `REPO_URL` to a read-only
deploy-key URL. The installer will:

- install Docker and clone the project to `/opt/melorin`;
- ask for the **main Telegram bot token** (from @BotFather) - the only bot configured at install time
  (or pass `MAIN_BOT_TOKEN=...`); reseller bots stay disabled until you enable the compose profile `reseller`;
- generate every secret (database, JWT, encryption key, service and metrics tokens, admin password) into `.env`;
- create the key pair for encrypted local backups;
- run database migrations and start all services.

It is safe to run again: an existing `.env` and backup key are never overwritten.

After it finishes:

1. Open `https://admin.example.com` and log in with the admin e-mail. The generated password is in
   `/opt/melorin/.env` as `MELORIN_BOOTSTRAP_ADMIN_PASSWORD`; change it at first login.
2. **Copy `/opt/melorin/secrets/backup/age-identity.txt` to a safe place off the server.** It is the only key that
   can decrypt the backups; without it they cannot be restored.
3. Configure panels, payments and other providers as described in `docs/`.

### Optional: SMTP and S3 backup

SMTP and off-site (S3-compatible) backup are **optional** and are configured later in the Admin panel under
*Settings -> Integrations*. Without SMTP, e-mail-code login is unavailable (the other login methods are not affected).
Backups are always written encrypted (age) to the local `api_storage` volume every day at 02:00 UTC; when S3 is
enabled in the Admin panel the encrypted file is also copied there.

### Updating

```bash
cd /opt/melorin && git pull --ff-only && docker compose build && docker compose run --rm api alembic upgrade head && docker compose up -d
```

### Operating

```bash
docker compose ps                         # service state
docker compose logs --tail=200 api worker telegram_main
curl https://shop.example.com/health/live
```

## Change log is mandatory

**Every change - code, configuration or server action - must be recorded in [docs/CHANGE_LOG.md](docs/CHANGE_LOG.md).**
Nobody has to remember to do it: on every push to `main` the `Changelog` GitHub workflow writes an entry for each
commit that has none. But you are still expected to give the reason. Put these single-line trailers in your commit
message (`make setup-git` installs a template) and they become the entry:

```
Problem: what was wrong / the error
Action:  what was changed to fix it
After:   how it was verified
Before:  how it behaved before        (optional)
Area:    api | bot | infra | ...      (optional)
```

Each entry records **before**, **problem/error**, **action taken**, **after (verified result)** and who/when.
Auto-generated entries never invent facts - missing fields say "not provided". Never put secrets in the log.
Details: [CONTRIBUTING.md](CONTRIBUTING.md). This applies equally to people, contractors and AI assistants.

## Quick start (local development)

```bash
cp .env.example .env
# set MELORIN_JWT_SECRET, MELORIN_ENCRYPTION_KEY, bootstrap admin values
make setup-git                    # optional: commit template for change-log trailers
docker compose up -d --build
docker compose run --rm api alembic upgrade head
curl http://localhost/health/live
```

For a clean local preflight, run `make install-verify`. It creates `.venv`,
installs the pinned API requirements, imports the Core app, and compiles the
API/tests. It does not claim PostgreSQL, Redis, Docker, provider, Telegram, or
restore evidence.

For the migration gate, run `make migration-smoke` inside the API environment.
It upgrades a PostgreSQL database to head and verifies the recorded Alembic
revision. Downgrade of the initial baseline is intentionally blocked.

The initial bootstrap migration is included; review and replace its metadata bootstrap with explicit Alembic diffs before future schema changes. API docs: `http://localhost/docs`.

## Layout

- `apps/api/melorin`: FastAPI Core, pure domain, modules, adapters, worker.
- `docs`: architecture source, ADR/open decisions, operations runbook.
- `infra`: reverse proxy and deployment files.
- `scripts`: server installer, backup/restore scripts, change-log automation, smoke tests.
- `.github/workflows`: `ci.yml` (lint, compile, tests, migration and build quality gates) and `changelog.yml` (automatic change log).
- `docs/CHANGE_LOG.md`: **change log - every change must be recorded** (see below).

## Scope delivered

Identity/linking, StoreContext, catalog/pricing/coupons, double-entry wallet/ledger, reseller debt limit, payment adapters/manual receipts, order state machine, Sanaei/PasarGuard/Mock provisioning adapters, retry/manual review/reconciliation, referral/commission reversal, test-account concurrency policy, tickets, notifications/outbox, audit/security, flags/settings, admin and reseller API surfaces, Docker Compose, CI and runbook.

## Production warning

This is a runnable backend foundation, not a claim that external credentials, gateway contracts, DNS, TLS, panel versions, financial open decisions, or production restore tests are complete. Resolve `docs/DECISIONS.md`, generate/review migrations, configure secrets, add the UI/channel apps, and run the full SRS E2E/security/resilience suite before production traffic.

## v1.1 implementation status

The backend now implements the decisions in the v1.1 documentation pack:

- Store-scoped currency, wallets and payment destinations. Checkout is wallet-first; external/manual payment only tops up the current Store wallet.
- Core-enforced Coupon scope, quotas, per-customer limits, time windows, maximum discount, Store/domain ownership and single-coupon selection.
- First-touch referral attribution, Admin-configurable per-plan commission/reward rules, refund reversal and future-commission clawback.
- Verified-email identity linking with conflict review records, no silent account merges, and V1 prohibition of VPN ownership transfers.
- ARQ + Redis worker entrypoint, idempotent transactional outbox, signed/replay-protected outgoing webhooks with retry, delivery log and endpoint auto-disable.
- Store-isolated Reseller API credentials with scopes, lifecycle, rate limits, IP allowlist and one-time secret display.
- PasarGuard adapter aligned with the current `/api/user/by-username`, `/api/user/by-id`, `/api/user/from_template`-compatible API family and PGClockBot's authentication/payload conventions.

Run the migration before starting traffic:

```bash
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d
curl http://localhost/health/ready
```

The remaining deployment inputs are intentionally environment-specific: real secrets, domain/TLS, PasarGuard credentials and group IDs, payment credentials/destinations, and a tested backup/restore target. The supplied PGClockBot repository is MIT-licensed beta code and was used as an adapter/API reference, not copied wholesale into Core.

Release status is authoritative in `docs/RELEASE-EVIDENCE-MATRIX.md`. Historical
phase and finding reports describe changes, not approval; the matrix remains
fail-closed until runtime and production evidence is attached. The current API
map is `docs/API-IMPLEMENTATION.md`, and the migration head is
`0008_bot_store_bindings`. Do not mark a phase report as current status.
