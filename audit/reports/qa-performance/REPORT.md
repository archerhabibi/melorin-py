# Audit report — AI-08 QA & Performance

## 1. Executive summary
- Status: in progress. QA-001..QA-003 are fixed; broader integration coverage and performance review remain open.
- Base: `audit/07-migration-ci-20261124` at `ed4b2ae`.
- QA-002 follow-up base: `audit/08-fix-flaky-order-fixture-20261124` at `e0fb336`.

## 2. Reviewed
- PostgreSQL CI failure in run 45077001718, attempt 1.
- Shared order fixture `tests/_db.py` and the referral commission test that creates 61 orders.
- PostgreSQL wallet property test, development requirements and PostgreSQL CI lane.
- Order idempotency contract and the real purchase/renewal race paths in PostgreSQL.

## 3. Method
- Inspect the failed CI attempt and force two distinct UUIDs to share their first six characters to reproduce the collision.
- Run the regression on SQLite and PostgreSQL, and rerun the originally affected referral test on PostgreSQL.
- Check the installed test dependencies and run the property test with Hypothesis on an isolated PostgreSQL 16 instance.

## 4. Findings
### QA-001 — Shared order fixture can generate duplicate order numbers
- Severity: Medium. Status: Fixed.
- Evidence: CI run 45077001718, attempt 1 failed on `uq_orders_number`; attempt 2 passed. The new deterministic test failed on the base with the same unique-constraint error.
- Cause: `make_order` used only the first six random hexadecimal characters of a UUID as a unique order number. A test creating many orders could generate the same value twice.
- Fix: the fixture now uses the application's sequence-backed six-character order-code generator when a number is not explicitly supplied. Explicit fixture numbers are preserved.
- Regression: forced repeated UUID prefixes now pass on SQLite and PostgreSQL; the originally affected PostgreSQL referral test also passes.

### QA-002 — Wallet property test silently skipped in the PostgreSQL CI lane
- Severity: Medium. Status: Fixed.
- Evidence: `tests/service/test_wallet_properties_db.py` uses `pytest.importorskip("hypothesis")`, but Hypothesis is absent from the hash-locked development requirements installed by CI. The PostgreSQL lane therefore skipped the property test even when `TEST_PG_URL` was configured.
- Effect: randomly generated sequences of credits, debits and idempotency-key replays were not checking ledger balance, overdraft protection or orphan transactions in CI.
- Fix: pin Hypothesis in the development input, regenerate the universal hashed lock, and import it normally so an incomplete test installation fails collection instead of silently skipping. The test still correctly skips on SQLite, where the documented PostgreSQL-only rollback property cannot be proved.
- Regression: the property test passed on isolated PostgreSQL 16 with `max_examples=25`; the regenerated lock has the same digest on Windows and Linux. Missing Hypothesis now fails test collection.

### QA-003 — Order concurrency contract never ran
- Severity: Medium. Status: Fixed.
- Evidence: `tests/contracts/test_order_idempotency_contract.py` unconditionally skipped its runtime case and referred to a live PostgreSQL/Redis fixture that it never used.
- Fix: remove the placeholder and run actual independent-session purchase and renewal races in the existing PostgreSQL CI lane. Deterministic barriers force both requests past the initial lookup before they contend; the assertions check the returned order, one charge, balanced entries and one paid event.
- The new tests exposed BE-003; three renewal replay cases failed on the base and passed after the fix. A different key still correctly receives `RENEWAL_IN_PROGRESS`.

## 5. Changes
- `tests/_db.py` and `tests/service/test_order_fixture.py`; no production code or schema change.
- `requirements-dev.in`, the generated `requirements-dev.txt` and `tests/service/test_wallet_properties_db.py`; test dependencies only.
- `tests/contracts/test_order_idempotency_contract.py` and `tests/postgres/test_order_idempotency_postgres.py`; the order service fix is recorded under BE-003.

## 6. Test results
- Forced collision: failed before the fix and passed afterwards on SQLite.
- PostgreSQL 16: forced collision and the original referral test passed (2 tests).
- Full `make test` with Hypothesis installed: 2,927 passed, 25 skipped (including the PostgreSQL-only race cases).
- PostgreSQL wallet property test: 1 passed (`max_examples=25`); lock check and `make lint` passed.
- Order concurrency and related renewal/contract tests: 35 passed on PostgreSQL 16.

## 7. Residual risks
- Wallet property coverage runs in the PostgreSQL lane; the live integration and staging-only browser skips need separate review.
- Full cross-system and load testing has not yet been completed.

## 8. Needs a human decision
- None for the test fixture correction.

## 9. Pull request
- Branch `audit/08-fix-flaky-order-fixture-20261124`; parent `audit/07-migration-ci-20261124`.
- QA-002 follow-up: branch `audit/08-wallet-properties-ci-20261124`; parent `audit/08-fix-flaky-order-fixture-20261124`.
- QA-003 / BE-003 follow-up: branch `audit/01-order-idempotency-races-20261124`; parent `audit/08-wallet-properties-ci-20261124`.
