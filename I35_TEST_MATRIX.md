# I35: test matrix and runtime evidence

Added `scripts/test_matrix.py` with explicit `unit`, `integration`, and `all`
groups. The default group excludes tests marked `integration`; the integration
group is never silently substituted with mocks.

Run `python scripts/test_matrix.py unit`, then run
`python scripts/test_matrix.py integration` in CI/staging with PostgreSQL,
Redis, Docker and provider credentials. Set `MELORIN_COVERAGE=0` when a
coverage plugin is unavailable.
