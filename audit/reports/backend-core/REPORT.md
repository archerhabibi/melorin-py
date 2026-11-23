# Audit report — AI-01 Backend & Core

(Structure follows section 7 of the execution plan.)

## 1. Executive summary
- Status: audit of the contract surface done; 1 finding confirmed and fixed (BE-001). No other confirmed finding in the scope and method below.
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

## 5. Changes
- `core/limits.py` new; `core/errors.py`, `core/pagination.py`; bounds in admin, catalog, notifications, referral, reports, reseller, vpn_accounts, eventcenter schemas/routers; regenerated `packages/api-client/openapi.json` and `docs/STATUS.md`.

## 6. Test results
| Command | Result | Notes |
|---|---|---|
| `pytest -n 2 -m "not integration" tests/http tests/contracts tests/service` (SQLite) | PASS | 1504 passed, 1 skipped, 193 s |
| `ruff check`, `ruff format --check`, `mypy` (391 files), `lint-imports` | PASS | |
| `gen_api_client.py --check`, `gen_docs.py --check` | PASS | |
| CI `quality`, `postgres-lane`, `web-e2e` on the PR | see PR | |

## 7. Residual risks
- The bounds are generous but a product decision (`MAX_MONEY = 10**13`, `MAX_DAYS = 36500`, ...): adjust in `core/limits.py`.
- `DataError` -> 422 could present a server-side arithmetic overflow as a client error; it is logged at WARNING with the exception type.

## 8. Needs a human decision
- Confirm the numeric bounds in `core/limits.py`.

## 9. Pull request
- Branch `audit/01-backend-core`, base `audit/00-baseline`, PR https://github.com/archerhabibi/melorin-py/pull/161
