# I53: J08 Readiness Semantics and Healthchecks

`/health/live` remains a lightweight liveness probe. `/health/ready` now means
ready to receive traffic: database connectivity, Redis availability, and a
fresh ARQ worker heartbeat must all pass. A stale or missing worker heartbeat
is treated as unavailable, and the endpoint returns HTTP 503 with diagnostic
check fields instead of HTTP 200 with a misleading degraded status.

Compose dependencies now wait for healthy API, web, and infrastructure
services before starting downstream services. This prevents Caddy, Telegram
runners, and Prometheus from starting against an API that has not completed
its dependency checks.
