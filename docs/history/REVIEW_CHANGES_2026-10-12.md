# Comprehensive review changes - 2026-10-12

Applied on top of `3b2262a` (33 files). Source: comprehensive project review.

## 1. Authentication and security
- Admin login: e-mail code replaced by password + TOTP (`AdminAuth.jsx`). `bootstrap` enables TOTP from `MELORIN_BOOTSTRAP_ADMIN_TOTP_SECRET` (required outside development).
- `issue_tokens` refuses inactive users (401).
- Rate limit fails closed (returns False) when Redis is unavailable in staging/production with `require_redis_rate_limit`; the local fallback multiplied the limit across workers.
- SSRF: VPN panel URL must be https and resolve only to public addresses (no private, loopback, link-local, reserved, multicast).
- Manual payment review only for `manual_card`; gateway payments are confirmed only by a valid callback (`PAYMENT_REVIEW_FORBIDDEN`).
- store-web: refresh token no longer kept in JS memory; cookie-based refresh (`credentials: include`) plus silent refresh on load.
- Telegram bot upload limit via `MELORIN_MAX_UPLOAD_BYTES` (default 5 MB).

## 2. Database and migrations
- `0001`: `bot_store_bindings` excluded from the frozen baseline; `0008` is its only owner.
- `0004`: skips the legacy global pending-user index when `target_store_id` exists; safer downgrade.
- `0009_referral_first_reward_guard` (new): `commissions.referred_user_id` (FK + index) and unique `(referred_user_id, kind)` so the first-order referral reward cannot be paid twice. Existing duplicate `signup_reward` rows are deleted.

## 3. Orders, provisioning and worker
- Admin retry uses `retry_generation` with a dedup key; the attempts counter is no longer reset.
- A `PROVISIONING` order younger than 15 minutes is not claimed by a second worker (`already_claimed`).
- arq: `panel_health_job` and `expiry_job` every 5 min, `near_expiry_job` every 15 min, `reconciliation_job` hourly, `privacy_retention_job` registered; `backup_job` timeout 900 s; `max_tries = 1`.
- `PATCH /products/{id}` uses `ProductPatch` (partial update, `is_active` editable).

## 4. Observability and Redis
- Redis timeouts: connect 1.5 s, operation 2.0 s; `/ready` ping/get capped at 2.5 s.
- `/metrics` refreshes `MelorinRedisUnavailable`, `MelorinWorkerStale` and `melorin_worker_last_tick` before each scrape.
- `alerts.yml`: `> 5m` corrected to `> 0` with `for: 5m`.

## 5. Docker and deployment
- Dockerfile: base `slim-bookworm`, `postgresql-client-16` from PGDG (matches `postgres:16`).
- `docker-compose.yml`: `mem_limit`/`cpus` per service, single-file age recipients mount, Caddy under profile `local-proxy`.
- `docker-compose.external.yml` (new): loopback ports 18000/18080/18081 for hosts that already own 80/443.
- `install_server.sh`: `EXTERNAL_PROXY=true` mode, random bootstrap TOTP secret, `BACKUP_OFFSITE_URI` optional; local encrypted backups work without S3 and Admin can enable off-site copy, atomic `secrets/metrics-token`, runs `python -m melorin.cli bootstrap`.
- `run_quality_gate.sh`: adds `npm audit --include=dev`.

## 6. Tests
New/updated: `test_i14_i22_regressions.py` (K11-K27 and full-audit regressions), `test_h013_baseline_contract.py`, `test_j04`, `test_k01`.

## Before deploy
- Admin cannot log in without TOTP: take the secret from the server `.env` and register it in an authenticator app.
- Off-site S3/rclone backup is optional in production; local encrypted backups are created by default and off-site copy is enabled later from Admin -> Settings -> Integrations.
- Rate limit is fail-closed: a Redis outage rejects rate-limited requests (e.g. login).
- Status: Python compile and shell syntax checks pass. Full test suite and web builds remain environment-dependent; the repository now includes a CI-backed PostgreSQL migration smoke that verifies head 0009 and its schema contract.


## L-03 regression fixes

The eight reported regressions are addressed: readiness and worker heartbeat contracts, operational control markers, correctness-focused Ruff policy, bounded Redis fallback, repository-root concurrency smoke discovery, production Fernet/HTTPS validation, and multi-store Telegram runner source contracts.


## L-04/L-05 completion

The Ruff gate now uses a correctness-focused rule set while retaining format verification. CI runs the migration smoke against PostgreSQL and verifies Alembic head `0009_referral_first_reward_guard`, the new `commissions.referred_user_id` column, and the unique referral reward constraint. Migration duplicate cleanup is deterministic even when timestamps tie.


## L-06/L-15 completion

Installer retries are now safe through atomic `.env.tmp` publication, EXTERNAL_PROXY routing is documented, manual bootstrap and integration steps are documented, PostgreSQL 16 backup tooling is pinned, provider and Telegram acceptance smoke gates are explicit, transient Telegram/Core failures replay without advancing offsets, production Redis rate limiting is fail-closed, and both frontend audits remain in the quality gate.


## L-16/L-22 completion

Restore verification and isolated restore-drill paths are documented and pinned to PostgreSQL 16 tooling. Telegram healthchecks now call `getMe`, metrics tokens remain file-backed, resource limits are explicit, phase reports are separated under `docs/history/`, and a live refresh-cookie/CORS smoke check was added.
