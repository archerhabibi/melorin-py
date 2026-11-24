# Audit report — AI-08 QA & Performance

## 1. Executive summary
- Status: in progress. QA-001 is fixed; integration coverage and performance review remain open.
- Base: `audit/07-migration-ci-20261124` at `ed4b2ae`.

## 2. Reviewed
- PostgreSQL CI failure in run 45077001718, attempt 1.
- Shared order fixture `tests/_db.py` and the referral commission test that creates 61 orders.

## 3. Method
- Inspect the failed CI attempt and force two distinct UUIDs to share their first six characters to reproduce the collision.
- Run the regression on SQLite and PostgreSQL, and rerun the originally affected referral test on PostgreSQL.

## 4. Findings
### QA-001 — Shared order fixture can generate duplicate order numbers
- Severity: Medium. Status: Fixed.
- Evidence: CI run 45077001718, attempt 1 failed on `uq_orders_number`; attempt 2 passed. The new deterministic test failed on the base with the same unique-constraint error.
- Cause: `make_order` used only the first six random hexadecimal characters of a UUID as a unique order number. A test creating many orders could generate the same value twice.
- Fix: the fixture now uses the application's sequence-backed six-character order-code generator when a number is not explicitly supplied. Explicit fixture numbers are preserved.
- Regression: forced repeated UUID prefixes now pass on SQLite and PostgreSQL; the originally affected PostgreSQL referral test also passes.

## 5. Changes
- `tests/_db.py` and `tests/service/test_order_fixture.py`; no production code or schema change.

## 6. Test results
- Forced collision: failed before the fix and passed afterwards on SQLite.
- PostgreSQL 16: forced collision and the original referral test passed (2 tests).
- Full `make test` is run separately on this branch.

## 7. Residual risks
- Property-based wallet tests still require Hypothesis and the PostgreSQL lane; the live integration and staging-only browser skips need separate review.
- Full cross-system and load testing has not yet been completed.

## 8. Needs a human decision
- None for the test fixture correction.

## 9. Pull request
- Branch `audit/08-fix-flaky-order-fixture-20261124`; parent `audit/07-migration-ci-20261124`.
