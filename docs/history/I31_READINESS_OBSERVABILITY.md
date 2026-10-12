# I31: readiness and worker observability

`/health/ready` now checks PostgreSQL, Redis reachability, pending/processing
outbox volume, and enabled panels with non-healthy status. It reports
`degraded` when Redis is unavailable and exports outbox/panel gauges.

Each ARQ polling tick records `melorin_worker_last_tick`, giving operations a
real worker heartbeat signal instead of the old static dashboard placeholder.
