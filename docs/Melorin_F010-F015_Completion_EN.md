# Melorin F010-F015 Completion

F010 remains hardened with Store-scoped order/payment idempotency, database uniqueness, concurrent unique-race recovery, row locks, and external payment intent persistence before provider calls.

The follow-on hardening closes the remaining reliability/security surface: worker and webhook claims now have a ten-minute lease recovery path, webhook enqueue is duplicate-safe before insert, refund remains a locked idempotent no-op on repeats, and regression tests cover HMAC timestamp replay bounds, bounded retry backoff, and SSRF-sensitive webhook URL rejection. The existing webhook delivery path keeps redirects disabled, validates DNS-resolved private IPs before delivery, uses signed event IDs, and caps retries with auto-disable after repeated failures.

Verification: Python compile and AST parsing passed. Live PostgreSQL/Redis, npm, Docker, provider, and webhook receiver execution were unavailable, so runtime integration evidence is not claimed.
