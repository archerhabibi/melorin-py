# I62: Observability and Alerting

J16 now has explicit alert state and Prometheus rules. The API emits
deduplicated firing/resolved alert gauges for database, Redis, stale worker
heartbeat, unhealthy enabled VPN panels, and a configurable outbox backlog
threshold. State changes retain a timestamp, severity, summary, and details
for operational inspection.

Prometheus loads `infra/alerts.yml` and evaluates critical infrastructure
alerts plus warning-level panel/backlog alerts. Recovery is automatic when
the API reports the condition as resolved; notification routing remains an
environment-specific Prometheus Alertmanager concern and is intentionally not
hard-coded into Core.
