# I52: J07 Redis Outage Rate-Limit Policy

J07 was a policy bug: when Redis failed, every production request to a
rate-limited endpoint received HTTP 429, including every login attempt.

The limiter now executes `INCR` and `EXPIRE` through one Redis transaction and
falls back to a bounded process-local fixed-window limiter during a Redis
outage. This preserves a per-process abuse ceiling without globally locking
out all users. Readiness exposes `rate_limit=local_degraded` while Redis is
unavailable, so operations can alert and recover the coordination layer.

The existing production setting remains meaningful as the requirement for
coordinated Redis rate limiting; it no longer converts infrastructure failure
into a misleading user-facing 429 storm.
