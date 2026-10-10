# I54: J09 Operational Endpoint Authentication

Metrics are now protected inside the API, not only by Caddy. Outside
development, `/metrics` requires `Authorization: Bearer
MELORIN_METRICS_TOKEN`; Prometheus reads the same secret from the mounted
`secrets/metrics-token` file.

Readiness remains usable by an orchestrator without credentials, but its
response is now terse. Database, Redis, worker, outbox, and panel details are
returned only with `X-Melorin-Health-Token`. Both tokens are required at
startup outside development and must be at least 32 characters.
