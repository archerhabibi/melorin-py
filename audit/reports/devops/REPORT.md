# Audit report — AI-07 DevOps & Reliability

## 1. Executive summary
- Status: in progress. OPS-001 through OPS-003 are fixed; the remaining CI, deployment and recovery review is not complete.
- Base: `audit/06-worker-db-retry-20261124` at `920b939`.

## 2. Reviewed
- `.github/workflows/ci.yml`: PostgreSQL services and integration test environment.
- `tests/postgres/test_migration_baseline.py`: disposable-database migration and ledger checks.
- `scripts/backup_restore_drill.sh`: temporary dump and database naming and cleanup.

## 3. Method
- Compare the CI environment with the test module's skip condition, then run that module on an isolated PostgreSQL 16 container with and without its admin URL.
- Reproduce a restore database-name collision on isolated PostgreSQL, then verify cleanup and simultaneous encrypted restores with synthetic data.

## 4. Findings
### OPS-001 — CI skips the migration baseline integration tests
- Severity: Medium. Status: Fixed.
- Evidence: CI invokes `pytest -m integration` without `TEST_PG_ADMIN_URL`; all three current tests in `test_migration_baseline.py` were skipped under that condition. With the variable set, all three passed on a disposable local PostgreSQL 16 server.
- Effect: CI did not exercise the empty-database upgrade, schema comparison, downgrade/re-upgrade or database-enforced ledger immutability in those tests.
- Cause: the integration job starts PostgreSQL but does not pass the admin URL required by the test module.
- Fix: provide the service's existing test-only PostgreSQL account and `postgres` database to the integration step. The tests create and drop only their randomly named scratch databases.

### OPS-002 — Restore cleanup can delete an unowned database
- Severity: High. Status: Fixed.
- Evidence: a pre-existing scratch database with the drill's timestamp-derived name was deleted when `createdb` failed; this was reproduced on an isolated PostgreSQL 16 instance. Two drills within a second also shared the same database and plaintext dump names.
- Effect: a failed or overlapping drill could remove a database it did not create, overwrite another run's dump, or make its restore fail. The affected name is limited to the drill's database prefix; no production data was used in testing.
- Cause: one-second timestamps named both resources, and the exit trap always removed the named dump and database even before successful creation.
- Fix: atomically allocate a private temporary directory and a random database name for each invocation; drop a database only after this invocation successfully created it. Report cleanup errors and fail the drill instead of reporting success with resources left behind.

### OPS-003 — Retention removes files outside the backup job's scope
- Severity: High. Status: Fixed.
- Evidence: in an isolated temporary directory, the main backup deleted expired panel backups and unrelated nested files; after fixing that path, the panel backup still deleted matching archives in nested directories.
- Effect: running backup retention can destroy unrelated files or another backup type stored under the configured backup directory.
- Cause: main retention selected every expired file recursively; panel retention selected matching files recursively.
- Fix: restrict each job to its own archive and checksum patterns at the top level of the backup directory. Regression tests use synthetic backups and verify both pruning and preservation.

## 5. Changes
- `.github/workflows/ci.yml` integration-step environment. No application schema or runtime change.
- Isolated restore-drill resources and added failure, cleanup and simultaneous-run regressions to the existing CI shell test.

## 6. Test results
- Backup retention regression: reproduced separate failures for the main and panel jobs on the original code; both preservation and pruning scenarios pass after the fix.
- Without `TEST_PG_ADMIN_URL`: 3 skipped, reproducing the CI omission.
- With the admin URL on the isolated test container: 3 passed, including migration round trips and ledger protections.
- Restore-drill shell tests: existing 3 scenarios plus 5 resource-ownership and cleanup scenarios passed.
- On isolated PostgreSQL with synthetic data and real age encryption: a forced database collision preserved the existing row; two concurrent restores passed using different databases and left no temporary databases or dumps.

## 7. Residual risks
- GitHub Actions itself must still run the updated workflow. The broader operations, backup and restore audit is not complete; no production backup was restored in this test.

## 8. Needs a human decision
- None for the test-only service configuration.

## 9. Pull request
- Branch `audit/07-migration-ci-20261124`; parent `audit/06-worker-db-retry-20261124`.

- OPS-002: PR #198.
- OPS-003: branch audit/34-backup-retention-e6a4711e; parent audit/33-restore-isolation-e40eb2ee.
