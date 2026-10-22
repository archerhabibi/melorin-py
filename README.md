# Melorin

Production-oriented modular monolith for a multi-store VPN platform: a main store, resellers with their own stores, domains and
Telegram bots, wallet-first checkout, and automatic provisioning on Sanaei / PasarGuard panels.

> فارسی: [README.fa.md](README.fa.md)

## What runs where

| Component | Path | Role |
|---|---|---|
| Core API (`api`) | `apps/api/melorin` | FastAPI; the only owner of PostgreSQL and of every business rule |
| Worker (`worker`) | `apps/api/melorin/worker` | ARQ + Redis: outbox, provisioning retries, expiry, panel health, reconciliation, daily encrypted backup |
| Store web (`store_web`) | `apps/store-web` | Customer storefront, dashboard, reseller console (React + Vite + Tailwind) |
| Admin web (`admin_web`) | `apps/admin-web` | Admin panel (React + Vite + Tailwind) |
| Main bot (`telegram_main`) | `apps/telegram-main` | Main Telegram bot; transport only, talks to Core |
| Reseller bots (`telegram_reseller`) | `apps/telegram-reseller` | One process hosting every reseller bot; driven by Core, no restart needed when a reseller is added or edited |
| PostgreSQL 16 / Redis 7 | compose | Financial source of truth / queues, rate limits, worker heartbeat |
| Caddy | `infra/Caddyfile` | TLS and routing (compose profile `local-proxy`; off in external-proxy mode) |
| Prometheus + Alertmanager | `infra/` | Metrics, alert rules, delivery to Telegram and/or e-mail |

Channels (web apps, bots) never touch the database and never implement pricing, wallet, order, payment or provisioning rules;
they call Core.

## Quick install (one line)

**Recommended resources:** 4 GB RAM and 2 vCPU - Ubuntu 22.04+ (the container memory caps add up to 3.5 GiB; see the runbook)

**Have these ready before you install:**

1. **Store domain** (the sales site, e.g. `shop.example.com`) - an A record pointing at the server IP
2. **Admin domain** (the admin panel, e.g. `admin.example.com`) - an A record pointing at the server IP
3. **Admin e-mail** (the login name of the first admin)
4. **Telegram bot token** from @BotFather

Ports **80 and 443 must be free** (Caddy obtains the TLS certificates automatically). Nothing else is asked.

Run as root on the server:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/get.sh)
```

The command downloads the project to `/opt/melorin`, registers the `melorin` command and opens the menu.
Choose **1) Install**; it asks only for the store domain, the admin domain, the admin e-mail and the bot token (hidden input), checks
that both domains point at this server, then installs everything unattended. At the end it prints the one-time
admin password and TOTP seed - save them immediately.

### Script menu (`melorin.sh`)

After installation the same menu opens at any time with `melorin` (or `bash /opt/melorin/melorin.sh` inside the project folder):

| Option | Action |
|---|---|
| `1` Install | Quiet install -> asks store domain, admin domain, admin e-mail, bot token |
| `2` Update | Pull the latest code, rebuild, run migrations, restart (`.env` is kept) |
| `3` Edit .env | Change bot token / store domain / admin domain, or open `.env` in an editor |
| `4` Web panel | Store and admin URLs, health check, admin password reset, IP-allowlist break-glass |
| `5` Service | Container status / start / stop / restart / logs |
| `6` Status | Health summary (version, bot, containers, API readiness, disk, memory, backup key) |
| `7` Uninstall | Complete removal (type `DELETE` to confirm) |
| `0` Exit | Leave the menu |

Shortcuts without the menu: `melorin status`, `melorin update`, `melorin restart`, `melorin logs [service]`, `melorin panel`.

Environment overrides for the one-liner (all optional): `REPO_REF` (branch, tag or commit; default `main` = latest;
pin a reviewed tag/commit for strict production control), `REPO_URL` (e.g. a private fork or read-only deploy-key URL), `APP_DIR` (default `/opt/melorin`).

### Non-interactive / advanced install

The menu calls `scripts/install_server.sh`, which can also be run directly (for automation):

```bash
curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/scripts/install_server.sh -o install.sh
# Verify the downloaded script against the release checksum before running it.
sha256sum install.sh
DOMAIN=shop.example.com ADMIN_DOMAIN=admin.example.com ADMIN_EMAIL=you@example.com REPO_REF=<reviewed-commit-or-tag> bash install.sh
```

If the repository is private, copy `scripts/install_server.sh` to the server and set `REPO_URL` to a read-only
deploy-key URL. When run directly, always set `REPO_REF` yourself (the script carries its own built-in default pin, which is
not necessarily the release you want); for strict production control use a reviewed commit or release tag instead of a moving branch. The installer will:

- install Docker and clone the project to `/opt/melorin`;
- take the **main Telegram bot token** (from @BotFather) - the only bot configured at install time (the menu passes it for you;
  directly it is read from the interactive prompt or `MAIN_BOT_TOKEN=...`; prefer the prompt so the token is not exposed in shell history or process listings);
- generate every secret (database, JWT, encryption key, service and metrics tokens, per-runner bot secrets, admin password) into `.env`;
- create the key pair for encrypted local backups;
- run database migrations, start all services, and install the automatic change recorder (cron, see below).

It is safe to run again: an existing `.env` and backup key are never overwritten.

**Reseller bots need no install-time setup.** The `telegram_reseller` container is always on; it asks Core which reseller
bots to run and idles while there are none. Add a reseller, its domain and its bot token in the Admin panel
(Admin -> Resellers); tokens are stored encrypted in the database and no restart or `.env` change is needed.

After it finishes:

1. Open `https://admin.example.com` and log in with the admin e-mail you entered. The installer prints the one-time password and removes it from `.env` immediately after bootstrap; save it securely and change it at first login. Admin sign-in uses TOTP (add the printed seed to an authenticator).
2. **Copy `/opt/melorin/secrets/backup/age-identity.txt` to a safe place off the server.** It is the only key that
   can decrypt the backups; without it they cannot be restored.
3. Configure panels, payments and other providers from the Admin panel as described in `docs/`.

### Existing reverse proxy (EXTERNAL_PROXY)

If another service already owns ports 80/443, the menu detects it and offers this mode automatically (or install with `EXTERNAL_PROXY=true`). The installer then binds only loopback ports: store `127.0.0.1:18080`, admin `127.0.0.1:18081`, and API `127.0.0.1:18000`. Route `/api/*` and `/health/*` to the API, and route each hostname to its matching web port. Reseller store domains go to the store port as well; if your proxy issues certificates on demand, gate them with `GET 127.0.0.1:18000/api/v1/tls/ask?domain=<host>` (200 = registered reseller domain, 404 = refuse).
The admin IP allowlist is optional and OFF by default; nothing is asked at install time. To restrict the admin API, use Admin panel -> Settings -> Integrations -> "Admin access (IP allowlist)". If you lock yourself out: `docker compose exec -T api python -m melorin.cli disable-admin-ip-allowlist`. During updates, keep using the same compose override: `docker compose -f docker-compose.yml -f docker-compose.external.yml up -d --build`.
Production secrets are one-time/bootstrap or runtime-only values: keep `.env` root-owned with mode `600`, prefer Docker/host secret files, never pass tokens on the command line, and rotate any bot token that was exposed. The installer removes the bootstrap password and TOTP seed after bootstrap. If the admin password is lost, reset it without putting it in shell history: `docker compose exec -T api python -m melorin.cli reset-admin-password admin@example.com`.

The installer validates inputs before publishing `.env`; a failed run leaves no partial new environment file. It creates the encrypted local-backup key, runs `alembic upgrade head`, starts the stack, and runs the idempotent admin bootstrap. Save the printed one-time TOTP seed in an authenticator. The installer removes both bootstrap credentials from `.env` after bootstrap.

## Optional: SMTP, Google / Telegram login, S3 backup

These are **optional** and are configured at runtime in the Admin panel under *Settings -> Integrations* (no rebuild, no `.env` edit):

- **SMTP** - without it, e-mail-code login is unavailable (the other login methods are not affected).
- **Google sign-in** - Google Identity Services ID-token flow; only a Client ID is needed. Guide: [docs/GOOGLE-LOGIN-SETUP.md](docs/GOOGLE-LOGIN-SETUP.md).
- **Telegram login** - OIDC / bot-approved website login. Guides: [docs/TELEGRAM-LOGIN-SETUP.md](docs/TELEGRAM-LOGIN-SETUP.md), [docs/TELEGRAM-WEB-LOGIN.md](docs/TELEGRAM-WEB-LOGIN.md).
- **Off-site (S3-compatible) backup** - backups are always written encrypted (age) to the local `api_storage` volume every day at 02:00 UTC; when S3 is
  enabled the encrypted file is also copied there.

## Updating

Simplest: run `melorin` and choose **2) Update** (pulls the latest code, rebuilds, migrates and restarts; `.env` is kept).
This always builds on the host.

### Automatic deployment (CI-gated)

`.github/workflows/deploy.yml` deploys **only after a successful `CI` run on a push to `main`**, and it deploys exactly the
commit CI tested. A manual run (*Deploy -> Run workflow*) re-checks that the ref is on `main` and has a green CI run.
The workflow streams `scripts/deploy.sh` to the server over SSH, which:

1. takes a lock and refuses to run over hand-edited tracked files;
2. takes an encrypted pre-deploy database backup (aborts if that fails);
3. builds the images (or pulls them in registry mode), runs `alembic upgrade head`, starts the stack;
4. waits for `/health/ready` (database + Redis + worker heartbeat) and for every core service to be healthy;
5. on any failure **automatically restores the previous commit**, rebuilds and re-verifies (exit code 1 = rolled back, 2 = rollback failed, intervene).

Set it up once:

1. On the server create a user that owns `/opt/melorin` and is in the `docker` group (`adduser --disabled-password deploy`,
   `usermod -aG docker deploy`, `chown -R deploy:deploy /opt/melorin`).
2. Create a dedicated SSH key pair, add the public key to that user's `authorized_keys`, and get the host key with
   `ssh-keyscan -t ed25519 -p 22 SERVER_IP`.
3. In GitHub (Settings -> Secrets and variables -> Actions) create the secrets `DEPLOY_HOST`, `DEPLOY_USER`,
   `DEPLOY_PORT`, `DEPLOY_SSH_KEY` (private key) and `DEPLOY_KNOWN_HOSTS`. Keep the private key only there.
4. Run the workflow once from the Actions tab and check it is green.

Optional **registry mode** (build once in CI, pull on the server, never build on production): set the repository variable
`DEPLOY_IMAGE_REGISTRY` (e.g. `ghcr.io/<owner>/melorin`) and the same `MELORIN_IMAGE_REGISTRY` in the server's `.env`.
Details, fallbacks and rollback behaviour: [docs/RUNBOOK.md](docs/RUNBOOK.md).

Manual deploy or rollback on the server (same code path as the workflow):

```bash
cd /opt/melorin && scripts/deploy.sh --ref <sha-or-tag>    # an older ref = rollback; add --db-downgrade only if the downgrades are real
```

Rollback restores **code**; the schema stays at the new revision unless `--db-downgrade` is given.

## Operating

Use `melorin` (menu 5 and 6) or the commands below:

```bash
docker compose ps                         # service state (add -f docker-compose.external.yml in external-proxy mode)
docker compose logs --tail=200 api worker telegram_main telegram_reseller
curl https://shop.example.com/health/live # liveness; /health/ready also needs Redis and a fresh worker heartbeat
scripts/ops_log.sh                        # add a note (before / problem / action / after) to the server log
```

- **Alerts:** Prometheus and Alertmanager ship in the compose stack. Set at least one receiver in `.env` - Telegram
  (`ALERT_TELEGRAM_BOT_TOKEN`, `ALERT_TELEGRAM_CHAT_ID`) and/or e-mail (`ALERT_SMTP_*`, `ALERT_EMAIL_TO`); otherwise alerts are evaluated but delivered nowhere.
  `/metrics` needs a bearer token and is blocked on the public hostnames.
- **Backups:** daily, encrypted, 30-day retention by default. A weekly GitHub workflow (`restore-drill.yml`) restores the newest off-site backup into a
  scratch database to prove it works; it is skipped until its secrets are set. Keep the age identity **off the server**.
- **Memory:** every container has a cap and the caps sum to 3.5 GiB (hence the 4 GB recommendation); CI fails if a service has no cap.
- **Incidents** (PostgreSQL, Redis, panels, gateways), release checks, rollback, reseller domains and supply-chain notes: [docs/RUNBOOK.md](docs/RUNBOOK.md).
  Note: while Redis is down in staging/production nobody can sign in (rate limiting fails closed on purpose).

## Change log is mandatory

**Every change - code, configuration or server action - must be recorded.** Nobody has to remember to do it,
because it is recorded automatically, but you are still expected to give the reason:

| Where | Recorded automatically by | You add the reason with |
|---|---|---|
| `docs/CHANGE_LOG.md` (code in git) | the `Changelog` GitHub workflow on every push to `main` | commit-message trailers `Problem:` `Action:` `After:` (`Before:`, `Area:`; `make setup-git` installs a template), or edit the entry |
| `var/ops-log.md` on the server | `scripts/ops_watch.sh` (cron, every 5 min: new deployed commit, `.env` key changes - names only, hand-edited files, container restarts/crashes) and the deploy workflow | `scripts/ops_log.sh` |

Each entry records **before**, **problem/error**, **action taken to fix it**, **after (verified result)** and who/when.
Auto-generated entries never invent facts - missing fields say "not provided". Never put secrets in a log.
Details: [CONTRIBUTING.md](CONTRIBUTING.md). This applies equally to people, contractors and AI assistants.

## Local development

Requirements: Docker with Compose, Python 3.12, Node 22.

```bash
cp .env.example .env
# set MELORIN_JWT_SECRET (32+ chars), MELORIN_ENCRYPTION_KEY (a Fernet key), bootstrap admin values
make setup-git                    # optional: commit template for change-log trailers

# Without the bundled Caddy; the override publishes loopback ports (store 18080, admin 18081, API 18000)
docker compose -f docker-compose.yml -f docker-compose.external.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.external.yml run --rm api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.external.yml exec -T api python -m melorin.cli bootstrap   # idempotent first admin
curl http://127.0.0.1:18000/health/live
```

API docs (`/docs`) are served only when `MELORIN_ENV=development`, and the bundled Caddy hides them on its hostnames, so open
`http://127.0.0.1:18000/docs` directly. To try the bundled proxy locally, start the stack with `COMPOSE_PROFILES=local-proxy`.

Run the apps without Docker (needs PostgreSQL and Redis from `.env`):

```bash
make api        # uvicorn with reload
make worker     # ARQ worker
cd apps/store-web && npm ci && npm run dev     # same for apps/admin-web
```

### Checks

| Command | What it does |
|---|---|
| `make install-verify` | Clean local preflight: creates `.venv`, installs the pinned API requirements, imports the Core app, compiles API and tests. Makes no claim about PostgreSQL, Redis, Docker, providers, Telegram or restore evidence |
| `make lint` | import-linter layering contracts, `ruff check`, `ruff format --check` |
| `make test` | API test suite (`apps/api`), SQLite in memory by default |
| `make guards` | Static guards: G001-G010 checks, quality config, ops/memory budget, generated docs up to date |
| `make quality-gate` | The full local gate CI mirrors (runtime/secret/frontend/release-matrix checks, guards, compile, lint, `npm audit`, web lint/format, unit matrix) |
| `make web-lint` / `make web-format` | ESLint / Prettier for both web apps |
| `make api-client` | Refresh the OpenAPI snapshot and regenerate, type-check and test `packages/api-client` |
| `make docs` | Regenerate `docs/STATUS.md` and the route tables in `docs/API.md` |
| `make migration-smoke` | Upgrade a PostgreSQL database to head and verify the recorded revision (run inside the API environment) |

Test lanes: the default suite runs on in-memory SQLite; `TEST_PG_URL=postgresql+asyncpg://...` runs the same tests on PostgreSQL
(private schema per test, plus the concurrency tests SQLite cannot prove); `pytest -m integration` needs PostgreSQL and Redis.
The web apps use Vitest (`npm test`), the bots have their own tests under `apps/telegram-main/tests`.
CI enforces a backend coverage floor that is only allowed to go up. See [docs/09-Testing.md](docs/09-Testing.md).

Database changes need an Alembic migration (`make revision`); CI runs `alembic upgrade head` and `alembic check` against an empty
PostgreSQL. Downgrade of the initial baseline is intentionally blocked.

## Layout

- `apps/api/melorin`: FastAPI Core, pure domain, kernel (ORM models), infrastructure, feature modules, channel adapters, worker.
  Layering is enforced by import-linter: `domain` <- `kernel` <- `core` <- feature `modules`; `channels/*` are adapters and never import admin, reseller, reports or the worker.
- `apps/admin-web`, `apps/store-web`: the two React web apps (see below).
- `apps/telegram-main`, `apps/telegram-reseller`: main Telegram bot and the reseller-bot supervisor.
- `packages/api-client`: typed client boundary generated from Core's OpenAPI snapshot (`openapi.json`); CI fails when the snapshot is stale. It is not yet a dependency of the web apps.
- `docs`: requirements, architecture, design records, runbook, decisions, generated status (see *Documentation* below).
- `infra`: Caddyfile, Prometheus config and alert rules, Alertmanager entrypoint.
- `get.sh`, `melorin.sh`: one-line installer entry point and the server management menu.
- `scripts`: server installer, deploy with rollback, backup/restore and restore-drill scripts, change-log and server-log automation, guards, smoke and evidence tools.
- `secrets`: runtime secret files mounted into containers (only `*.example` placeholders are committed).
- `.github/workflows`: `ci.yml` (dependency audit, hash-lock check, guards, lint, unit/integration/PostgreSQL-lane tests, migration and E2E smoke, web lint/test/build/bundle budget, api-client check, image builds), `deploy.yml` (CI-gated deploy with rollback), `changelog.yml` (automatic change log), `pin-images.yml` (base-image digest pins), `restore-drill.yml` (weekly restore proof). Dependabot covers pip, npm and Docker.
- `docs/CHANGE_LOG.md`: **change log - every change must be recorded** (see above).

## Web apps

Both apps are React + Vite + Tailwind CSS 4 with right-to-left Persian UI, self-hosted Vazirmatn font, light/dark themes and a shared accessible
dialog hook (`useDialog`: focus trap, Esc, focus restore, scroll lock). Local build check: `cd apps/<app> && npm ci && npm run build`.

**Store web (`apps/store-web`)** - catalog and wallet-first purchase, wallet top-up with receipts, dashboard (VPN accounts, orders, referral, tickets,
notifications), subscription / purchase-result page, account inquiry, Google / Telegram / e-mail login, and the reseller console and pricing screens
(lazy-loaded). A reseller's own domain serves the same storefront under that store's name.

**Admin panel (`apps/admin-web`)** - route-level code splitting; the sales-infrastructure screens (Panels, Sales bundles, Products) share one
visual language (`src/kit.jsx` + the "Infra v2" block in `src/styles.css`): connected KPI bar that doubles as a filter, a sales-readiness ring,
ring gauges and segmented capacity meters, status stripes on cards (green = can sell, red = cannot, grey = off), "problems first" sorting and a
cards/table toggle on every list. Further screens cover resellers and their applications, payments and receipts, tickets, identity-link
reviews, infrastructure health, and the Google / Telegram login and other integration settings.

Frontend quality gates (CI and `make quality-gate`): ESLint 9 (react, hooks, jsx-a11y) with a **warning ratchet** (`--max-warnings` in each
`package.json`; it only goes down), Prettier format check, Vitest, `npm audit`, lockfile verification, and per-app **first-load JS budgets**
enforced by `scripts/check_bundle_budget.py` after the build.

## Scope delivered

Identity and linking (e-mail code, password + TOTP, Google, Telegram bot and OIDC login, channel binding, verified-email linking with conflict
review), StoreContext and store isolation, catalog with sales bundles and per-store pricing, coupons, double-entry wallet/ledger, reseller debt limit,
reseller applications (two-step, via web or bot) with per-store domains and on-demand TLS, payment adapters (manual card receipts, Zarinpal), order state machine,
Sanaei / PasarGuard / Mock provisioning adapters, retry / manual review / reconciliation, referral and commission reversal, test-account concurrency policy,
tickets, notifications and transactional outbox, signed outgoing webhooks, Reseller API, audit and security controls, flags and settings, admin and reseller
API surfaces, reports, metrics and alerting, encrypted backups with restore drills, Docker Compose, CI/CD with rollback, and the runbook.

Security posture in short: admin sign-in with TOTP; HttpOnly refresh cookie with an in-memory access token; Redis-backed rate limiting that fails closed;
explicit CORS allowlists and security headers; bot runners with least-privilege secrets; hash-locked Python dependencies, `pip-audit` / `npm audit` in CI,
digest-pinned base images; encrypted (age) backups. Details: [docs/06-Security.md](docs/06-Security.md).

## Key behaviours (v1.1 decisions)

- Store-scoped currency, wallets and payment destinations. Checkout is wallet-first; external/manual payment only tops up the current Store wallet.
- Core-enforced Coupon scope, quotas, per-customer limits, time windows, maximum discount, Store/domain ownership and single-coupon selection.
- First-touch referral attribution, Admin-configurable per-plan commission/reward rules, refund reversal and future-commission clawback.
- Verified-email identity linking with conflict review records, no silent account merges, and V1 prohibition of VPN ownership transfers.
- ARQ + Redis worker, idempotent transactional outbox, signed/replay-protected outgoing webhooks with retry, delivery log and endpoint auto-disable.
- Store-isolated Reseller API credentials with scopes, lifecycle, rate limits, IP allowlist and one-time secret display.
- PasarGuard adapter aligned with the current `/api/user/by-username`, `/api/user/by-id`, `/api/user/from_template`-compatible API family and PGClockBot's authentication/payload conventions.

The remaining deployment inputs are intentionally environment-specific: real secrets, domain/TLS, PasarGuard credentials and group IDs, payment credentials/destinations, and a tested backup/restore target. The supplied PGClockBot repository is MIT-licensed beta code and was used as an adapter/API reference, not copied wholesale into Core.

## Documentation

| Need | Read |
|---|---|
| Index and requirements | [docs/00-README.md](docs/00-README.md), [docs/01-Requirements-SRS.md](docs/01-Requirements-SRS.md) |
| Architecture, technical design, data model, API contracts | `docs/02` - `docs/05` ; generated route list: [docs/API.md](docs/API.md) |
| Security, finance/order/provisioning, operations and DR, testing, roadmap | `docs/06` - `docs/10` |
| Channels, renewal, store isolation, channel binding, referral/coupon scope | `docs/11`, `docs/13`, `docs/14`, `docs/16`, `docs/17` |
| Operations runbook | [docs/RUNBOOK.md](docs/RUNBOOK.md) |
| Decisions and open items | [docs/DECISIONS.md](docs/DECISIONS.md) |
| Login setup | [docs/GOOGLE-LOGIN-SETUP.md](docs/GOOGLE-LOGIN-SETUP.md), [docs/TELEGRAM-LOGIN-SETUP.md](docs/TELEGRAM-LOGIN-SETUP.md) |
| Rules for changing docs | [docs/DOCUMENTATION-POLICY.md](docs/DOCUMENTATION-POLICY.md) |

When a setting, route, install step or security rule changes, update this README, `README.fa.md` and the runbook in the same change, then run `make docs`.

## Production warning

This is a complete, runnable platform foundation, not a claim that external credentials, gateway contracts, DNS, TLS, panel versions, financial open decisions, or production restore tests are complete. Resolve `docs/DECISIONS.md`, configure secrets, and run the full SRS E2E/security/resilience suite on a staging environment before production traffic.

Release status is authoritative in `docs/RELEASE-EVIDENCE-MATRIX.md`. Historical
phase and finding reports (kept in git tag `docs-history-2026-10-22`, indexed in `docs/HISTORY.md`) describe changes, not approval; the matrix
remains fail-closed until runtime and production evidence is attached. Current measurements
(migration head, API surface, test and coverage numbers) are in the generated
`docs/STATUS.md`; the route list is `docs/API.md`. Do not mark a phase report as current status.
