# I50: J05 Test Strategy and Coverage Gate

J05 identified a large gap between fast contract tests and the behavior that
matters at runtime. The test matrix is now explicit: `unit`, `integration`,
`concurrency`, and `all` are separate commands. Unit CI publishes XML
coverage and enforces a non-regressing 20% floor while the suite is expanded;
integration tests run against the PostgreSQL and Redis service containers.

The integration boundary includes an ASGI HTTP check, the existing live E2E
wallet-to-provisioning flow, and the PostgreSQL idempotency smoke. Concurrency
tests remain marked separately so they cannot be accidentally counted as unit
evidence. This is deliberately honest: the current 20% floor is a baseline,
not a claim that the project has reached the review's recommended 60%
financial-module target.
