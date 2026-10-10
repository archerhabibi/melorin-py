# Melorin F001-F010 Completion

## Verdict
F001, F006, F007, F008, F009 and the database portion of F010 are implemented in the cumulative baseline. F002-F005 remain blocked because the canonical repository contains only Web README boundaries, not the Store/Admin Web source trees or lockfiles; the Caddy contract is prepared, but a frontend build cannot honestly be claimed.

## Implemented
- F001: API and worker now build from repository root so Docker COPY paths are valid.
- F006: staging/production reject weak database credentials and weak bootstrap admin credentials.
- F007: secure backup script uses `PGPASSFILE`, not a password in process arguments.
- F008: encrypted backup artifact, SHA-256 sidecar, retention cleanup, optional off-host copy, and restore-oriented environment contract added.
- F009: uploads are read in bounded chunks, enforce the configured limit, and validate magic bytes.
- F010: payment/order idempotency is Store-scoped and protected by database uniqueness plus IntegrityError recovery; external payment intent is persisted before the provider call.

## Verification
Python compile and AST parsing pass. Shell syntax passes. Docker, PostgreSQL, Redis, npm, and live provider/restore execution were not available in this environment. The Web findings require the missing frontend source trees to finish deterministically.
