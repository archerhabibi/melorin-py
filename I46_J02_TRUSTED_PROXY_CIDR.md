# I46: J02 Trusted Proxy CIDR Handling

J02 was caused by exact-string matching of the reverse proxy socket address.
That failed in Docker because the Caddy container reaches the API from a
bridge-network address, so the real client address in `X-Forwarded-For` was
ignored.

The API now parses configured IPs and CIDRs, accepts forwarded addresses only
when the direct peer belongs to a trusted network, and walks chained proxy
headers from right to left. The same resolver is used by request context,
rate limiting, admin IP allowlists, and audit records, preventing those
controls from disagreeing.

Compose pins the backend network to `172.28.0.0/16`; the example environment
file documents the matching trusted proxy configuration. External deployments
must replace it with the exact reverse-proxy CIDR, not a broad internet-facing
range. Unit tests cover trusted CIDR, untrusted spoofing, chained proxies, and
invalid configuration entries.
