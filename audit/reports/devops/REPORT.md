# Audit report — AI-07 DevOps & Reliability

## 1. Executive summary
- Status: in progress. OPS-001 is fixed; the remaining CI, deployment and recovery review is not complete.
- Base: `audit/06-worker-db-retry-20261124` at `920b939`.

## 2. Reviewed
- `.github/workflows/ci.yml`: PostgreSQL services and integration test environment.
- `tests/postgres/test_migration_baseline.py`: disposable-database migration and ledger checks.

## 3. Method
- Compare the CI environment with the test module's skip condition, then run that module on an isolated PostgreSQL 16 container with and without its admin URL.

## 4. Findings
### OPS-001 — CI skips the migration baseline integration tests
- Severity: Medium. Status: Fixed.
- Evidence: CI invokes `pytest -m integration` without `TEST_PG_ADMIN_URL`; all three current tests in `test_migration_baseline.py` were skipped under that condition. With the variable set, all three passed on a disposable local PostgreSQL 16 server.
- Effect: CI did not exercise the empty-database upgrade, schema comparison, downgrade/re-upgrade or database-enforced ledger immutability in those tests.
- Cause: the integration job starts PostgreSQL but does not pass the admin URL required by the test module.
- Fix: provide the service's existing test-only PostgreSQL account and `postgres` database to the integration step. The tests create and drop only their randomly named scratch databases.

## 5. Changes
- `.github/workflows/ci.yml` integration-step environment. No application schema or runtime change.

## 6. Test results
- Without `TEST_PG_ADMIN_URL`: 3 skipped, reproducing the CI omission.
- With the admin URL on the isolated test container: 3 passed, including migration round trips and ledger protections.

## 7. Residual risks
- GitHub Actions itself must still run the updated workflow. The broader operations, backup and restore audit is not complete.

## 8. Needs a human decision
- None for the test-only service configuration.

## 9. Pull request
- Branch `audit/07-migration-ci-20261124`; parent `audit/06-worker-db-retry-20261124`.
