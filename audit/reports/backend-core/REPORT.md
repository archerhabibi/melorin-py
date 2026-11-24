# Audit report — AI-01 Backend & Core

(Structure follows section 7 of the execution plan.)

## 1. Executive summary
- Status: audit of the contract surface done; BE-001, the reseller wallet finding BE-002 and concurrent renewal finding BE-003 are fixed. The broader business-logic review is not complete.
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

## 5. Changes
- `core/limits.py` new; `core/errors.py`, `core/pagination.py`; bounds in admin, catalog, notifications, referral, reports, reseller, vpn_accounts, eventcenter schemas/routers; regenerated `packages/api-client/openapi.json` and `docs/STATUS.md`.

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

## 7. Residual risks
- The bounds are generous but a product decision (`MAX_MONEY = 10**13`, `MAX_DAYS = 36500`, ...): adjust in `core/limits.py`.
- `DataError` -> 422 could present a server-side arithmetic overflow as a client error; it is logged at WARNING with the exception type.

## 8. Needs a human decision
- Confirm the numeric bounds in `core/limits.py`.

## 9. Pull request
- Branch `audit/01-backend-core`, base `audit/00-baseline`, PR https://github.com/archerhabibi/melorin-py/pull/161
