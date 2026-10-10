# Melorin

Production-oriented modular monolith for a multi-store VPN platform. The implementation follows the supplied SRS and documentation pack.

## Quick start

```bash
cp .env.example .env
# set MELORIN_JWT_SECRET, MELORIN_ENCRYPTION_KEY, bootstrap admin values
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
- `.github/workflows/ci.yml`: lint, compile, tests, migration and build quality gates.

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
