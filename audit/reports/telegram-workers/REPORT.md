# Audit report — AI-06 Telegram & Workers

## 1. Executive summary
- Status: in progress. WRK-001 is fixed; the remaining worker and bot flows have not yet been fully reviewed.
- Base: `audit/05-reseller-wallet-be002-20261124` at `b26ea8a` (the follow-up to PR #165).

## 2. Reviewed
- `worker/runner.py`: outbox claiming, event processing, retry and notification state.
- `worker/arq_app.py`: polling and dispatch.
- `tests/service/test_worker_runner_db.py`: existing retry and delivery coverage.

## 3. Method
- Follow a claimed event through a failed SQLAlchemy flush and a failed SQL statement, then attempt the same event again.
- Exercise the failure and recovery on isolated SQLite and PostgreSQL databases.

## 4. Findings
### WRK-001 — A database error prevents normal retry accounting or commits partial work
- Severity: Medium. Status: Fixed.
- File / symbol: `worker/runner.py`, `process_event`.
- Evidence: with either an ORM flush or SQL statement failing on a uniqueness violation, both regression cases failed on the base in SQLite and PostgreSQL. An aborted session could not update the claimed event; on SQLite the preceding write could instead be committed.
- Effect: an event may remain `processing` until its ten-minute lease expires, without incrementing attempts or triggering the normal failure alert. Partial writes from a failed database operation may also persist.
- Cause: failure handling attempted to query and commit in the same failed database transaction.
- Fix: roll back database errors before reloading the event and recording the retry. Save and log only the database exception class, avoiding SQL parameters. An inactive session is also rolled back for non-database exceptions. Other non-database failures retain the existing notification-state behavior.
- Regression: both database failure paths roll back partial writes, record a pending retry and successfully process the event after recovery. A separate test preserves already-sent notification state when another recipient fails.

## 5. Changes
- `worker/runner.py` and `tests/service/test_worker_runner_db.py`. No schema change.

## 6. Test results
- SQLite worker service tests: 28 passed.
- PostgreSQL 16: both SQL failure paths and the sent-notification case passed (3 tests).
- `make lint`: passed; full `make test` is run separately on this branch.

## 7. Residual risks
- Telegram delivery and a database commit are not a distributed transaction: a message sent immediately before a database failure can be delivered again on retry.
- A database that remains unavailable cannot record a retry until connectivity returns. Other jobs and bot flows still need review.

## 8. Needs a human decision
- None for this narrowly scoped correction.

## 9. Pull request
- Branch `audit/06-worker-db-retry-20261124`; parent `audit/05-reseller-wallet-be002-20261124`.
