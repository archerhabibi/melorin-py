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
The database remains the financial source of truth. Rate-limit/coordination degrades to development fallback; restore Redis before scaling multiple workers.

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
