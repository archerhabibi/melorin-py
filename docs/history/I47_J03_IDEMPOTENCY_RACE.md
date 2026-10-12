# I47: J03 Concurrent Idempotency-Key Requests

The order idempotency pre-check was never sufficient by itself: concurrent
requests could both observe no row, then the loser failed during `flush()` on
the unique constraint and returned HTTP 500.

Order insertion is now wrapped in `AsyncSession.begin_nested()`. A losing
request rolls back only that savepoint, reads the committed winner, validates
that the request payload matches, and returns the same order. Reusing a key
for a different product, order kind, or VPN account still returns the explicit
`IDEMPOTENCY_KEY_REUSE` conflict.

The new regression coverage checks the savepoint/flush/recovery contract and
adds an opt-in integration marker for the real PostgreSQL/Redis concurrency
environment. The live E2E/concurrency job should run this against two or more
request sessions before release.
