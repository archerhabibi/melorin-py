# I25: rate-limit and login throttling

`X-Forwarded-For` is now trusted only when the direct peer is configured as a
trusted proxy. Direct clients cannot rotate that header to evade the IP
limiter.

Password login also has a per-account email throttle of 10 attempts per 15
minutes, in addition to the endpoint IP limit. Production deployments should
set `MELORIN_TRUSTED_PROXY_IPS` to the actual Caddy proxy addresses.
