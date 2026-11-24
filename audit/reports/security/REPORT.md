# Audit report — AI-02 Security

(Structure follows section 7 of the execution plan.)

## 1. Executive summary
- Status: first pass over authentication, authorization, rate limiting and exposure controls done. SEC-001 through SEC-005 are fixed; broader security review continues. The authorization perimeter is covered by a permanent matrix test.
- Base: stacked on `audit/01-backend-core` (`b0f7fd8`). Date: 2026-11-23.

## 2. Reviewed
- `core/{security,ratelimit,channel,middleware,config}.py`, `modules/identity/**` (sign-in, refresh rotation, admin invite, account linking), `app.py` (`/health`, `/metrics`, docs exposure), `infra/Caddyfile`, the 46 operations that do not use the bearer scheme, the 394 that do.
- Out of scope: provider adapters and webhooks (AI-04), frontend storage of tokens (AI-05), host hardening (AI-07).

## 3. Method
- Authorization matrix over the OpenAPI snapshot, executed against the app on a throw-away schema: anonymous; ordinary customer on `/admin/**`; customer on another store's `{store_id}`; credential-based public operations without their credential.
- Source reading of: JWT encode/decode (HS256 pinned, `exp/sub/iss/aud/jti` required), refresh rotation (reuse revokes the family, user-agent class check), constant-time comparisons (`compare_digest`, `safe_equal`), `/metrics` and `/health` protection, production secret validation, docs exposure.
- Limits: no real Telegram, Google or payment provider was contacted; Redis-outage behaviour and timing side channels were not measured; no external penetration test.

## 4. Findings
### SEC-001 — Per-key API rate limit stored but not enforced by default
- Severity: Low. Status: Fixed.
- File / symbol: `core/config.py: enforce_api_key_rate_limit` (default `False`), used in `core/channel.py:api_channel`.
- Evidence: each reseller API key carries `rate_limit_per_minute` (default 120) that the reseller sees, but `hit("apikey:<id>", ...)` only ran when an operator had switched the setting on; `.env.example` shipped it as `false`.
- Impact: a leaked or misbehaving key can send unlimited requests per minute; the limit shown in the UI is not the limit applied.
- Root cause: the control was introduced behind an opt-in flag (T54) and never made the default.
- Fix: default `true`; `.env.example`, docs/08 updated; opt-out stays (`MELORIN_ENFORCE_API_KEY_RATE_LIMIT=false`). While Redis is down every rate-limited API-key call answers 503 in staging/production (the policy of `core.ratelimit.hit`, unchanged). The earlier 429 statement in this report was incorrect.
- Regression test: `tests/service/test_api_key_channel.py::test_api_key_rate_limit_is_on_by_default_and_can_be_turned_off`.
- Dependencies: AI-01 (`core/config.py`) and AI-07 (`.env.example`) own the touched files; logged in AUDIT-TRACKER.

### SEC-002 — Cancelled password operations release worker capacity too early
- Severity: Medium. Status: Fixed. Base: `audit/10-order-request-identity-883d25e9` at `d6705de675b1f401ced2fe09d62854892be44d0c`.
- File / symbol: `core/security.py`, `hash_password` and `verify_password`.
- Evidence: with two password workers still blocked, cancelling their async callers allowed a third worker to start. This was reproduced for both hashing and verification; the two cancellation tests failed on the parent.
- Effect: cancellation can defeat the intended per-process KDF concurrency bound and increase CPU and memory pressure. The test proves task-cancellation behavior; it does not establish how a particular proxy or client causes cancellation.
- Root cause: the semaphore protected the awaited coroutine, whose cancellation does not stop the running thread.
- Fix: hold the slot until the executor future actually finishes, shield the worker from caller cancellation, preserve context propagation and consume worker errors when a cancelled caller is no longer waiting. Normal exceptions still reach active callers.
- Regression: deterministic thread-controlled tests cover cancellation and worker failures for both operations; existing authentication and authorization tests are also run. No API or schema change.

### SEC-003 — Password login accepts credentials changed during verification
- Severity: High. Status: Fixed. Base: `audit/11-security-883d25e9` at `47afc0b69e5fccf9dc390d54607664cd775e2782`.
- File / symbol: `modules/identity/routes/sign_in.py`, `password_login`.
- Evidence: when the password was changed in another transaction after verification, the old password still produced a session. A replacement hash with older parameters could also be overwritten by rehashing the old password. A changed email was likewise accepted; a concurrent deactivation reached a different failure path. Three original regression cases failed on the parent.
- Root cause: after locking and refreshing the user, the route did not compare the current credential and email with the values it had verified.
- Fix: calculate any hash upgrade before locking, then re-read the user under a row lock and reject a changed hash, changed email, inactive or deleted account before issuing tokens. The lock remains held through token issuance.
- Compatibility: a login overlapping an account change can be rejected; retry with the current credentials. No API or schema change.
- Regression: HTTP tests cover normal and legacy password replacements, deactivation, an email change and successful hash upgrades, using separate database sessions.

### SEC-004 — Password reauthentication accepts proof that has become stale
- Severity: High. Status: Fixed. Base: `audit/12-login-race-883d25e9` at `9ef547878d0892f89440153094850b93ad0f0902`.
- Files / symbols: `modules/identity/routes/account.py`, `change_admin_password`; `modules/identity/account_linking/reauth.py`, `require`.
- Evidence: after another transaction changed the password during verification, an admin password change overwrote the newer password, and an identity unlink accepted the old password. The same admin route continued after deactivation, demotion or removal of two-factor authentication. Six regression cases failed on the parent.
- Root cause: the password was verified against a user object read earlier, without locking and rechecking it before the protected action.
- Fix: finish password work before locking, reload the user under a row lock and compare the verified hash. Admin changes also recheck active/admin/two-factor state, access restrictions and the password policy against the refreshed email. Password-based unlinking holds the lock until its change commits.
- Compatibility: concurrent changes may now return 401 and require a retry with current credentials. No API or schema change.
- Regression: HTTP tests cover the stale password and account-state changes on SQLite and PostgreSQL; PostgreSQL concurrency tests verify that only one simultaneous admin password change succeeds and that unlink holds the user lock until commit.

### SEC-005 — Domain verification did not bind validation to its connection
- Severity: Medium. Status: Fixed. Base: PR #186 at 10b9a1b8dd1b74a7dddd4a7984c6780a8b164659.
- File / symbol: `modules/reseller/auto_verify.py`, `check_http`.
- Evidence: DNS was checked for public addresses but the HTTP client then received the hostname and performed another lookup. Four new address-pinning and TLS cases failed on the parent; mixed public/private DNS answers were already refused.
- Impact: a changed DNS answer could bypass the outbound address policy for the fixed domain-proof path. Valid TLS for the requested hostname was still required.
- Fix: validate all DNS answers, connect to one checked IPv4 or IPv6 address and retain the original HTTP Host, TLS SNI and certificate hostname. Refuse non-hostname inputs before resolving them.
- Regression: the domain-proof suite exercises address binding, mixed answers, malformed hostnames and real local TLS with matching and mismatched certificates. Existing body-size and proof-matching checks remain in place.
- Compatibility: an unreachable first checked address can delay proof until an existing scheduled retry; no API or schema change.

### Checked and not a defect
- Public sign-in routes look unthrottled by decorator but the `auth` router carries `RateLimit("auth", 30, 60)` and password sign-in adds per-account budgets (10/900 s per email+IP, 100/900 s per email).
- `/metrics` needs a bearer token (constant-time compare), production start-up rejects weak or empty tokens, `/docs` and `/openapi.json` are dev-only, and the Caddyfile blocks `/metrics`, `/docs`, `/redoc`, `/openapi.json` and `/api/v1/internal/*`.

## 5. Changes
- `core/config.py`, `.env.example`, `docs/08-IDENTITY-ACCOUNT-PERSON.md` (SEC-001).
- Identity input bounds (continuation of BE-001): `TelegramProfile.telegram_id` (and the 6 request models that inherit it), `GET /internal/identity/telegram/status ?telegram_id`, `GET /identity/history ?limit/?offset`.
- New tests: `tests/http/test_authz_matrix.py` (5 tests). Regenerated `openapi.json` and `docs/STATUS.md`.
- SEC-002 updates the KDF slot lifecycle and adds cancellation/worker-failure tests.
- SEC-003 updates password login and adds credential-change race tests.
- SEC-004 updates admin password changes and password-based unlink reauthentication, with concurrent PostgreSQL tests.

- SEC-005 updates domain-proof egress validation and adds address, hostname and TLS regression coverage.

## 6. Test results
| Command | Result | Notes |
|---|---|---|
| `pytest tests/contracts tests/service/test_api_key_channel.py tests/http/test_authz_matrix.py` | PASS | 522 passed, 1 skipped |
| `pytest -n 2 -m "not integration" tests/http tests/contracts tests/service` (SQLite) | PASS | 1509 passed, 1 skipped, 197 s |
| `ruff check`, `ruff format --check`, `mypy` (391 files), `lint-imports` | PASS | |
| `check_ops_p0`, `check_quality_config`, `check_g001_g010`, `check_release_matrix`, `gen_docs --check`, `gen_api_client --check` | PASS | |
| CI `quality`, `postgres-lane`, `web-e2e` | see PR | |
| SEC-002 focused KDF, authentication and authorization tests | PASS | 33 passed; the two cancellation cases failed on the parent |
| SEC-002 full backend suite | PASS | 2,939 passed, 32 skipped |
| SEC-002 lint, formatting and mypy | PASS | 8 import contracts kept; 391 source files type-checked |
| SEC-003 focused SQLite authentication and KDF tests | PASS | 55 passed on `9b2ffd8f`; 6 final credential/lock tests passed on `b9ed717b` |
| SEC-003 PostgreSQL authentication and account tests | PASS | 46 passed on `9b2ffd8f`; 6 final credential/lock tests passed on `b9ed717b` |
| SEC-003 lint, formatting and mypy | PASS | 8 import contracts kept; 391 source files type-checked |
| SEC-003 full backend suite | PASS | 2,944 passed, 32 skipped on `b9ed717b` |
| SEC-004 targeted SQLite and PostgreSQL HTTP tests | PASS | 8 passed on each database |
| SEC-004 PostgreSQL concurrency tests | PASS | 2 passed with independent transactions |
| SEC-004 lint, formatting and mypy | PASS | 8 import contracts kept; 391 source files type-checked |
| SEC-004 full backend suite | see PR | Final source revision tested in the background |
| SEC-005 focused domain and OCR security regressions | PASS | 34 passed; 4 new cases failed on the parent |
| SEC-005 make lint and mypy | PASS | 8 import contracts; 391 source files type-checked |

## 7. Residual risks
- SEC-005 uses the first checked address; another address is not attempted within the same proof request. Existing retries handle later attempts.
- The public Telegram web-login flow (`/auth/telegram/web/sessions*`) and provider callbacks are verified by code reading only, not by a live Telegram or gateway.
- The matrix proves who is rejected, not that every allowed response contains only the caller's own data; per-endpoint data scoping stays covered by the existing store-scope tests.

## 8. Needs a human decision
- Confirm that API-key calls should answer 503 while Redis is down (existing fail-closed policy) now that the limit is on by default.

## 9. Pull request
- Branch `audit/02-security`, base `audit/01-backend-core`.
- SEC-005 follow-up: branch `audit/21-domain-proof-089a80a5`; parent PR #186.
