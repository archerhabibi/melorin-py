# I20: reliable ARQ polling

Outbox polling no longer re-enqueues itself from inside the running job.
`poll_tick` is scheduled by an ARQ cron entry every two seconds with
`unique=True`, so a failed or restarted worker cannot leave a fixed-ID chain
stalled or create duplicate pollers.

The Makefile and Compose now use the same ARQ entrypoint. The PostgreSQL
outbox remains the source of truth and row leases make overlapping recovery
safe.
