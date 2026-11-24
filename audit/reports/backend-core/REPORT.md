# Audit report — AI-01 Backend & Core

(Structure follows section 7 of the execution plan.)

## 1. Executive summary
- Status: audit of the contract surface done; BE-001 through BE-009 are fixed. The broader business-logic review is not complete.
- Scope: request schemas, routers and error handling owned by AI-01 (`modules/{catalog,orders,vpn_accounts,loyalty,referral,tickets,reports,eventcenter,notifications,broadcast,reseller,admin,panelops}`, `core/{errors,pagination,limits}`).
- Base commit: `ee384d60ba89fa25b13a694545fc26b62e7ae14a` (branch `audit/01-backend-core` stacks on `audit/00-baseline`).
- Date: 2026-11-23.

## 2. Reviewed
- Paths: all request models and query/path parameters of the 440 operations in the committed OpenAPI snapshot; `core/errors.py` (global exception mapping), `core/pagination.py`.
- Out of scope here, handed over: `modules/identity/**` (AI-02), `modules/payments/schemas.py` (AI-03).

## 3. Method
- Scan of the OpenAPI snapshot for every integer a client can send (query, path, body fields, list items, dict values) without a minimum and a maximum; then reproduction on the real app (httpx ASGI harness, PostgreSQL 16).
- Extra ruff rule families beyond the project set (`ASYNC,S,B,RUF006,RUF012,PLW,BLE,PERF`) over `melorin/`: only 76 `except Exception` (resilience paths), 8 `global`, no actionable result.
- Limits: no line-by-line review of the business logic of all 13 modules; coverage is at the contract level.

## 4. Findings
### BE-001 — Unbounded client integers answer HTTP 500
- Severity: Low (authentication required, no data corruption; log amplification and 5xx noise). Status: Fixed.
- File / symbol: request schemas in 19+5 AI-01 files; `core/errors.py` (`DBAPIError` handler).
- Evidence: wallet top-up `amount` >= 2^63, `offset` >= 2^63 on `GET /stores/{id}/vpn-accounts` and `GET /identity/history` -> 500 with a traceback.
- Root cause: integers had `gt`/`ge` but no upper bound, and a client-caused `DataError` was mapped to 500.
- Fix: `core/limits.py` (single source of bounds); bounds on every AI-01-owned field; `DataError` -> 422 `VALUE_OUT_OF_RANGE` as a safety net; second pass for list items, dict values and path parameters that the first pass missed.
- Regression tests: `tests/contracts/test_openapi_input_bounds.py` (fails on any unbounded request integer; `PENDING` can only shrink), `tests/http/test_input_bounds_http.py`.
- Dependencies: `PENDING` still lists 9 items for AI-02 (telegram ids, identity history paging) and 10 for AI-03 (`payments/schemas.py`).

### BE-002 — Reseller wallet adjustment retries can fail or acknowledge a different operation
- Severity: High (financial operations may be reported successful for the wrong adjustment, or a committed correction may appear to fail). Status: Fixed.
- Base: `audit/05-frontend-fe001` at `dd7a50fb9783a32ea5b457ee04cbbfcb151da936`; file: `modules/reseller/routes/customers.py`, `adjust_customer_wallet_core`.
- Evidence: after a correction consumes the wallet balance, retrying the same idempotency key returned `INSUFFICIENT_FUNDS`; reusing a key for a different amount or customer returned HTTP 200 without applying that requested adjustment. Both HTTP regressions failed on the base.
- Cause: the balance check preceded the replay lookup, and the existing ledger transaction was accepted without checking its wallet and amount.
- Fix: lock the wallet before checking the balance and replay; permit an existing transaction through the balance check, and reject a reused key unless the ledger posting matches the requested wallet, amount and operation kind. A valid replay returns the existing transaction and current wallet balance.
- Regression: HTTP tests for a spent-balance retry and key reuse; PostgreSQL tests for simultaneous same-key and different-key corrections. On PostgreSQL 16 both parallel cases passed, with one debit and no negative balance.
- Limits: membership and configured amount-cap checks still precede replay, and the established API treats reason/reference as descriptive metadata rather than part of key identity.

### BE-003 — Concurrent renewal replay is rejected after the first request commits
- Severity: Medium. Status: Fixed.
- Base: `audit/08-wallet-properties-ci-20261124` at `c764b09`; file: `modules/orders/service/create.py`.
- Evidence: two PostgreSQL sessions pass the same-key precheck, then one waits on the account lock. After the first commits, the waiter reports `RENEWAL_IN_PROGRESS` instead of returning that same order. With the same key and another product or renewal mode it also reports the wrong error. Three regression cases failed on the base.
- Cause: the precheck runs before the account lock, while renewal eligibility is checked after the lock without checking whether the waiting request's key has since been committed.
- Fix: recheck the scoped idempotency key after acquiring the account lock and use the same request-identity validation for every replay recovery path, including a commit-time integrity failure. A different key still receives `RENEWAL_IN_PROGRESS`.
- Regression: deterministic PostgreSQL races cover a same-key purchase and four renewal cases, with one order, one charge, a balanced ledger and one paid event. Related renewal and contract tests pass on PostgreSQL.

### BE-004 — A same-key checkout can fail after its limited coupon is consumed
- Severity: Medium. Status: Fixed.
- Base: `audit/01-order-idempotency-races-20261124` at `1df34650bd8dbc68577d79812f9acb9cb8df6513`; file: `modules/orders/service/create.py`.
- Evidence: two PostgreSQL requests pass the idempotency lookup; one then waits for the coupon row while the other commits its order and consumes the last redemption. On the base, retries with the same key failed with `COUPON_EXHAUSTED` or `COUPON_CUSTOMER_LIMIT`, and a same-key request for another product received the coupon error instead of `IDEMPOTENCY_KEY_REUSE`. Three of four regression cases failed on the base.
- Cause: coupon validation happens after the initial replay lookup and can reject the waiting request before it reaches the unique-order constraint.
- Fix: if coupon validation raises an application error, recheck the scoped order and its existing identity validation. Return the committed order for a valid replay, reject a conflicting identity, and preserve the original coupon error when no order exists.
- Regression: `tests/postgres/test_order_coupon_race_postgres.py` covers total and per-customer limits, a different key and a different product, and checks one order, one redemption, a balanced ledger and one paid event.

### BE-005 — Different checkout details can be acknowledged as an earlier order
- Severity: Medium. Status: Fixed. Base: integration branch `audit/09-integrate-frontend-20261124` at `eba1442f70d6efe5475f66da493580478e4ba966`.
- File / symbol: `modules/orders/service/create.py`, `create_order` replay lookup. The key is scoped to a customer and store.
- Evidence on the base: changing the coupon, bundle, selected panel, account name or payment method while reusing a key returned the original order instead of a conflict; the HTTP checkout returned 201. Two simultaneous PostgreSQL requests with different account names both returned success for one order. Seven SQLite/HTTP regression cases and the PostgreSQL race failed before the fix.
- Effect: a client can be told that a different purchase succeeded even though its requested discount, destination or name was not used. The reproduced cases did not create a second charge.
- Root cause: replay validation compared only product, kind, account and renewal mode, while allocation can resolve or normalize other requested fields before storing the order.
- Fix: save the original request identity in the immutable pricing snapshot, normalize coupon codes as coupon lookup does, and compare it on every replay path. A different request or a legacy order without an identity is rejected with `IDEMPOTENCY_KEY_REUSE`. No schema migration is needed.
- Compatibility: existing orders created before this change lack an identity and cannot be replayed with their old key; retrieve the existing order instead. Otherwise clients must retry the same checkout details; coupon case and surrounding whitespace remain equivalent.
- Tests: service and HTTP coverage for matching and changed requests, default bundle resolution, coupon normalization and legacy orders; PostgreSQL coverage for concurrent insertion, renewal locking and exhausted-coupon recovery. Full results are recorded below after verification.

### BE-006 — Loyalty reward retries can fail or acknowledge a different reward
- Severity: Medium. Status: Fixed. Base: PR #179 at 04d7780d375e94f3a42c43916a49c337dfb9c12a.
- File / symbol: modules/loyalty/redemption.py, redeem.
- Evidence: on PostgreSQL, same-key concurrent redemptions returned insufficient points, sold-out or per-user-limit errors after the first completed. A concurrent same-key request for a different reward incorrectly returned the first reward as a success. Four race cases failed on the base; a replay after disabling the program also failed on SQLite.
- Root cause: the replay lookup was performed before waiting for the account lock, and the unique-key recovery path did not check the reward identity. The program-enabled check also preceded retrieval of an already completed redemption.
- Fix: reuse one scoped replay-and-identity check before program validation, after the account lock, and after a unique-key conflict. A new key still requires an enabled program and obeys stock, point and customer limits.
- Regression: tests/postgres/test_loyalty_replay_postgres.py exercises four race cases and a different-key control; the service suite exercises a replay after program disablement. One redemption, one points debit, one balanced wallet credit and the correct remaining balance are asserted.
- Compatibility: a conflicting same-key request now returns IDEMPOTENCY_KEY_REUSED (409); a retry of an already completed reward remains retrievable after the program is disabled. No schema migration.

### BE-007 — Loyalty adjustment retries can acknowledge a different amount
- Severity: Medium. Status: Fixed. Base: PR #180 at c2f361ccc65e370f3253e0ce07010578422b37a5.
- File / symbol: modules/loyalty/adjustments.py, adjust.
- Evidence: an administrator granted 80 points, then reused the same key with 120 or -10 points. HTTP returned 200 and the old 80-point transaction, without performing the requested adjustment. Both changed-amount PostgreSQL races and the HTTP regression failed on the parent.
- Root cause: the points ledger returns an existing transaction by key, but the adjustment caller did not verify its account, operation kind or amount.
- Fix: after the existing account lock and ledger lookup, reject a key whose stored account, kind or signed amount differs. Repeating the same adjustment returns the same transaction; a different key still applies a new adjustment. Reason remains descriptive audit metadata.
- Regression: tests/http/test_loyalty_http.py checks real responses, balances and audit counts; tests/postgres/test_loyalty_adjustment_race_postgres.py exercises same-key, changed-amount, opposite-sign and different-key races.
- Compatibility: changed amounts using an existing key now return IDEMPOTENCY_KEY_REUSED (409) rather than 200. No schema migration.

### BE-008 — Delayed completion can award rewards after refund
- Severity: High (a refunded order can produce spendable referral cash). Status: Fixed. Base: PR #181 at 02e3416dcfebc08a6c231565b4a12e1a94ad95f7.
- Files / symbols: modules/loyalty/earning.py and modules/referral/commissions.py, on_order_completed; worker/runner.py dispatches outbox events concurrently.
- Evidence: after a refund event was processed, a delayed completion event created three loyalty transactions and a cash commission on the already refunded order. Direct loyalty, referral and worker regressions all failed on the parent; both PostgreSQL refund/settlement orderings also failed.
- Root cause: both reward engines read the order without checking its current status or synchronizing with the order row lock already used by the refund path. A refund event could therefore observe no rewards and complete before a delayed settlement committed them.
- Fix: each reward engine reloads and locks the existing order row before awarding; it only settles a completed order. Refund and reward settlement now serialize. A refund that follows settlement still reverses both rewards in the existing order.
- Regression: tests/service/test_reward_event_order.py covers direct and worker-level out-of-order delivery; tests/postgres/test_reward_refund_race_postgres.py exercises both real row-lock orderings and checks points, cash and commission status.
- Compatibility: delayed events no longer award rewards for orders that are not completed. No API or schema migration.

### BE-009 — Replayed first purchases can pay two referral rewards
- Severity: High (a duplicate worker event creates a second spendable cash payout). Status: Fixed. Base: PR #182 at 7b17d7d1b4ec50ecde420506ca85cea01506c43d.
- File / symbol: modules/referral/commissions.py, on_order_completed.
- Evidence: when the signup reward is 500 and the commission is 300, replaying the same first completed order pays both amounts. The service regression and a two-worker PostgreSQL regression both failed on the parent.
- Root cause: the first delivery recorded a signup reward; a replay then selected the ordinary commission plan and the per-(order, kind) guard failed to recognize the original reward.
- Fix: after taking the existing order row lock, return if any commission row already exists for that order. The first and subsequent purchases still receive their respective plan once, including when worker deliveries overlap.
- Regression: tests/service/test_referral_replay.py covers repeated first and later purchases, their recorded rewards and wallet balances; tests/postgres/test_referral_replay_race_postgres.py runs competing deliveries against a real row lock.
- Compatibility: duplicate completion events no longer pay a different reward on the same order. No API or schema migration.

## 5. Changes
- `core/limits.py` new; `core/errors.py`, `core/pagination.py`; bounds in admin, catalog, notifications, referral, reports, reseller, vpn_accounts, eventcenter schemas/routers; regenerated `packages/api-client/openapi.json` and `docs/STATUS.md`.
- BE-004 changes order replay handling and adds PostgreSQL coupon concurrency regressions; no schema or API contract change.
- BE-005 records the checkout request identity in the existing order snapshot and verifies it for all replay paths; the API response and database schema are unchanged.

## 6. Test results
| Command | Result | Notes |
|---|---|---|
| `pytest -n 2 -m "not integration" tests/http tests/contracts tests/service` (SQLite) | PASS | 1504 passed, 1 skipped, 193 s |
| `ruff check`, `ruff format --check`, `mypy` (391 files), `lint-imports` | PASS | |
| `gen_api_client.py --check`, `gen_docs.py --check` | PASS | |
| CI `quality`, `postgres-lane`, `web-e2e` on the PR | see PR | |
| BE-002 focused HTTP tests | PASS | 2 failed on the base, 2 passed after the fix |
| BE-002 PostgreSQL concurrency tests | PASS | 2 passed against an isolated PostgreSQL 16 container |
| BE-003 order races and related renewal/contract tests | PASS | 35 passed on isolated PostgreSQL 16 |
| BE-003 `make lint`, `mypy`, full `make test` | PASS | 2,927 passed, 25 skipped in the SQLite/default lane |
| BE-004 coupon, order and renewal regressions (PostgreSQL) | PASS | 40 passed; 3 of 4 coupon-race cases failed on the base |
| BE-004 `make lint` | PASS | 8 import contracts kept; formatting and lint passed |
| BE-004 `mypy --config-file pyproject.toml` | PASS | 391 source files |
| BE-004 `PYTEST_ADDOPTS="-n 2" make test` | PASS | Earlier server run of the same code and regression file: 2,927 passed, 29 skipped |
| BE-004 independent `make test` rerun | PASS | 2,927 passed, 29 skipped; the four coupon race cases also ran in the PostgreSQL lane |
| BE-005 focused SQLite/HTTP, renewal and adapter tests | PASS | 64 passed; 7 relevant cases failed on the parent before the fix |
| BE-005 PostgreSQL checkout, renewal and coupon races, service and HTTP tests | PASS | 21 passed; the conflicting concurrent checkout failed on the parent before the fix |
| BE-005 `make lint` | PASS | 8 import contracts kept; lint and formatting passed |
| BE-005 `PYTEST_ADDOPTS="-n 2" make test` | PASS | 2,935 passed, 32 skipped on `e1dee522`; subsequent changes were documentation, formatting and an additional completed-order replay assertion |
| BE-005 final service and HTTP checks | PASS | 9 passed, including replay after provisioning |
| `gen_api_client.py --check`, `gen_docs.py --check` | PASS | API snapshot and generated docs unchanged |
| BE-006 loyalty concurrency regressions | PASS | PostgreSQL: 5 passed after the fix; 4 failed on the parent. SQLite: 33 loyalty service and 8 HTTP tests passed; mypy and make lint passed |
| BE-006 full make test | PASS | 2,951 passed, 39 skipped on the PR #180 code tree |
| BE-007 focused regressions | PASS | PostgreSQL: 4 passed, including 2 races failing on the parent; SQLite: 42 loyalty service/HTTP tests passed; mypy and make lint passed |
| BE-007 full make test | PASS | 2,952 passed, 43 skipped on the PR #181 code tree |
| BE-008 focused regressions | PASS | 2 PostgreSQL race scenarios and 45 loyalty/referral service tests passed; 9 loyalty HTTP tests, mypy and make lint passed |
| BE-008 full make test | PASS | 2,955 passed, 45 skipped on the PR #182 code tree |
| BE-009 focused regressions | PASS | 14 service tests and 3 PostgreSQL races passed; the new replay and race tests failed on the parent. make lint and mypy passed |

## 7. Residual risks
- The bounds are generous but a product decision (`MAX_MONEY = 10**13`, `MAX_DAYS = 36500`, ...): adjust in `core/limits.py`.
- `DataError` -> 422 could present a server-side arithmetic overflow as a client error; it is logged at WARNING with the exception type.

## 8. Needs a human decision
- Confirm the numeric bounds in `core/limits.py`.

## 9. Pull request
- Branch `audit/01-backend-core`, base `audit/00-baseline`, PR https://github.com/archerhabibi/melorin-py/pull/161
