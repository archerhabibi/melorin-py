# Audit report — AI-06 Telegram & Workers

## 1. Executive summary
- Status: in progress. WRK-001 and WRK-002 are fixed; the remaining worker and bot flows have not yet been fully reviewed.
- Base: `audit/05-reseller-wallet-be002-20261124` at `b26ea8a` (the follow-up to PR #165).

## 2. Reviewed
- `worker/runner.py`: outbox claiming, event processing, retry and notification state.
- `worker/arq_app.py`: polling and dispatch.
- `tests/service/test_worker_runner_db.py`: existing retry and delivery coverage.

## 3. Method
- Follow a claimed event through a failed SQLAlchemy flush and a failed SQL statement, then attempt the same event again.
- Exercise the failure and recovery on isolated SQLite and PostgreSQL databases.
- Run overlapping poll jobs with shared worker context, an independently failing row, and cancellation while rows wait for a slot.

## 4. Findings
### WRK-001 — A database error prevents normal retry accounting or commits partial work
- Severity: Medium. Status: Fixed.
- File / symbol: `worker/runner.py`, `process_event`.
- Evidence: with either an ORM flush or SQL statement failing on a uniqueness violation, both regression cases failed on the base in SQLite and PostgreSQL. An aborted session could not update the claimed event; on SQLite the preceding write could instead be committed.
- Effect: an event may remain `processing` until its ten-minute lease expires, without incrementing attempts or triggering the normal failure alert. Partial writes from a failed database operation may also persist.
- Cause: failure handling attempted to query and commit in the same failed database transaction.
- Fix: roll back database errors before reloading the event and recording the retry. Save and log only the database exception class, avoiding SQL parameters. An inactive session is also rolled back for non-database exceptions. Other non-database failures retain the existing notification-state behavior.
- Regression: both database failure paths roll back partial writes, record a pending retry and successfully process the event after recovery. A separate test preserves already-sent notification state when another recipient fails.

### WRK-002 — Overlapping poll ticks bypass the per-worker concurrency limit
- Severity: Medium. Status: Fixed.
- File / symbol: `worker/arq_app.py`, `poll_tick` and `startup`.
- Evidence: three new regressions fail on the parent implementation: overlapping ticks exceed eight active rows, a failed row lets the tick finish while a sibling still runs, and queued row coroutines are constructed before a slot is available. ARQ `unique=True` deduplicates a scheduled time, not different scheduled times.
- Effect: slow rows can multiply active database sessions and external requests within a worker; work can outlive its tick or leave unawaited coroutines on cancellation.
- Fix: initialize a guard in the worker startup context shared by ARQ job copies. A busy worker skips a new poll before claiming rows but refreshes its heartbeat. A batch waits for all sibling results before propagating an error, and constructs each row coroutine only after obtaining a slot. Cancellation retains the guard until running siblings finish cleanup.
- Regression: overlapping ticks, continued heartbeats, row failure, cancellation cleanup and startup wiring are covered. The eight-row bound is per worker process; adding workers increases total parallelism intentionally.

## 5. Changes
- `worker/runner.py`, `worker/arq_app.py`, and worker service and unit tests. No schema change.

## 6. Test results
- SQLite worker service tests: 28 passed.
- PostgreSQL 16: both SQL failure paths and the sent-notification case passed (3 tests).
- `make lint`: passed; full `make test` is run separately on this branch.
- WRK-002: three failures reproduced on the parent; 47 focused worker tests and `make lint` passed after the fix. Full `make test` is running on the test server.

## 7. Residual risks
- Telegram delivery and a database commit are not a distributed transaction: a message sent immediately before a database failure can be delivered again on retry.
- A database that remains unavailable cannot record a retry until connectivity returns. Other jobs and bot flows still need review.
- Claimed rows interrupted by worker cancellation still rely on the existing ten-minute lease recovery. A heartbeat during a skipped poll indicates a live worker, not an empty backlog.

## 8. Needs a human decision
- None for this narrowly scoped correction.

## 9. Pull request
- Branch `audit/06-worker-db-retry-20261124`; parent `audit/05-reseller-wallet-be002-20261124`.
- WRK-002 follow-up branch `audit/39-worker-poll-d5cdff38`; parent `audit/38-ocr-response-d5cdff38`.
