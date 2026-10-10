# Full project audit after I41

## Fixed in this pass

The API now publishes the worker heartbeat through Redis with a short TTL,
readiness and Admin health read that shared signal, and the product form uses
IRT instead of the stale IRR default. Zarinpal's refund annotation now matches
its actual return type, and external gateway destinations consistently use
manual-review semantics.

## Fixed in the I42 pass

Admin dashboard (`App.jsx`) was rewritten: it previously read tokens from
`localStorage` although login keeps them in memory only, so every call after
sign-in returned 401. All Admin calls now go through `src/api.js` (`authFetch`,
in-memory bearer token, single transparent refresh on 401). Hard-coded Persian
date replaced by a live date; Google Fonts import removed; Redis and Worker
status now come from `/admin/health`; the non-functional "manual order" button
was removed. Dockerfiles fall back to `npm install` only when no lockfile
exists, CI checks the lockfile before `npm ci`, and `scripts/gen_web_locks.sh`
generates the real lockfiles. Regression test: `test_i42_admin_token_storage.py`.

## Runtime pass (2026-10-10, real execution)

Fixed after actually installing and running everything:
* 0003 migration failed on a fresh database (constraint name differs); now idempotent by column set.
* `orders.vpn_account_id` FK was never created (CreateTable skips use_alter FKs); new migration 0005. `alembic check` is clean.
* Email-code login crashed (500) for users without an email Identity (bootstrap admin); service links the identity, bootstrap creates it.
* `backup_secure.sh` rejected the app's `postgresql+asyncpg://` URL.
* 6 ruff errors; 22 failing tests (wrong ROOT path, two stale assertions); `test_matrix.py` ran pytest from the wrong directory.
* Store hero card showed fabricated network stats (route, ping, days left); replaced with neutral copy.
* Real `package-lock.json` files generated; `npm ci` + build pass.

Verified by running: fresh `alembic upgrade head`, bootstrap (idempotent), API + ARQ worker, `scripts/e2e_smoke.py`, outbox replay without duplicate accounts, both web builds, admin login/dashboard in headless Chromium, encrypted backup and restore drill, quality gate (71 tests, ruff clean).

## Remaining risks

* Docker/Compose images were not built (no Docker daemon in the review environment).
* Telegram bots, Zarinpal sandbox, real Sanaei/PasarGuard panels, Prometheus: no runtime evidence.
* Test coverage is ~8% line coverage; the E2E script is the main behavioural test. Add integration tests.
* `/metrics` is served by the API itself; only Caddy hides it. Keep the API port unpublished.
* Admin session is memory-only: a reload requires signing in again.
* Release matrix stays **Blocked** until the items above have evidence.
