# Melorin operations runbook

## Deploy
1. Put production secrets in the secret manager, never `.env` in git.
2. `docker compose pull && docker compose build`.
3. Take a DB backup and run `docker compose run --rm api alembic upgrade head`.
4. `docker compose up -d`; verify `/health/live` and `/health/ready`.
5. Check worker logs and a controlled staging purchase.

## PostgreSQL failure
Stop writes at Caddy or disable the `purchase` and `payment` feature flags. Restore the latest encrypted backup to a new instance. Run migrations and integrity checks, then re-enable in staging first.

## Redis failure
The database remains the financial source of truth. In staging/production, rate limiting fails closed while Redis is unavailable; this prevents a multi-worker bypass. Restore Redis and verify `/health/ready` before reopening login traffic or scaling workers.

## Panel failure
Panel health becomes unhealthy; provisioning selects no server and sends orders to manual review. Do not refund until Panel state is reconciled. Use admin retry or attach an existing account.

## Gateway / callback incident
Payment callback is idempotent. Inspect `payment_attempts`, never manually edit payment status without audit and ledger compensation.

## Data corruption
Disable affected feature, preserve DB and audit logs, export evidence, restore to isolated DB, run reconciliation and migration tests. Never delete ledger/audit rows.

## Backup policy
Default is 1 run/day, 30-day retention, encrypted local plus off-server copy. A backup is not considered valid until a scheduled restore test passes.

## v1.1 release checks

1. Set non-development JWT, encryption, bot and database secrets. Never use the checked-in defaults.
2. Configure each PasarGuard panel with `group_ids`, verify TLS, and run the Admin panel health check. Use a restricted PasarGuard credential that can create/modify/read users only.
3. Configure a payment destination for every Store. A reseller Store must never inherit the Main Store destination.
4. Run `alembic upgrade head`, then exercise wallet top-up, duplicate callback, wallet-only checkout, coupon quota concurrency, reseller debt-limit boundary, refund/clawback and webhook retry tests.
5. Verify ARQ/Redis queue health and PostgreSQL outbox recovery after a worker restart.
6. Perform a real restore drill and record RPO <= 24h and RTO <= 8h before enabling production sales.


## Acceptance smoke

Run `MELORIN_RUN_EXTERNAL_PROVIDERS=1 scripts/integration_smoke.sh` with a real panel URL and sandbox payment credentials before selling. Run `MELORIN_RUN_TELEGRAM_SMOKE=1 scripts/integration_smoke.sh` with a rotated BotFather token to verify Telegram. Record the results with `scripts/ops_log.sh`; do not paste secrets into ClickUp, logs, or reports.


## Session and backup acceptance

For a live deployment, run `BASE_URL=https://shop.example.com COOKIE_JAR=... python scripts/auth_cookie_smoke.py` to verify refresh-cookie rotation, HttpOnly protection, and same-origin CORS behavior. Run `scripts/backup_restore_verify.sh` for archive verification and `scripts/backup_restore_drill.sh` against an isolated PostgreSQL 16 database for a real restore drill.

## Reseller store domains (Caddy)

A reseller's domain is served by the bundled Caddy as soon as the store exists: the reseller points an `A`/`AAAA` record at this server, and on the first HTTPS visit Caddy asks Core (`GET /api/v1/tls/ask?domain=<host>`) whether the name is an active reseller store domain; only then does it request a certificate (on-demand TLS). Unknown names get no certificate. The domain shows the reseller's storefront (the web app resolves the store from the hostname via `/api/v1/stores/by-domain/<host>`), never the admin panel.

Checks: `docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile`; from inside the network `curl -s -o /dev/null -w '%{http_code}' 'http://api:8000/api/v1/tls/ask?domain=shop.example.com'` (200 registered, 404 otherwise). If a certificate does not appear, check DNS first, then the Caddy log for the ACME error (rate limits, port 80/443 reachability). With `EXTERNAL_PROXY=true` the bundled Caddy is off: route reseller domains to the store port in the host proxy and gate on-demand certificates with the same ask URL.
