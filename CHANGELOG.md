# Changelog

- `@melorin/api-client`: متد `raw(path, init)`؛ `authFetch` و `useCall` در admin-web روی آن اجرا می‌شوند (ترنسپورت واحد).

All notable changes to Melorin. The detailed, dated engineering log lives in
[docs/06-ARCHITECTURE-DECISIONS.md](docs/06-ARCHITECTURE-DECISIONS.md) ("Melorin Change Log"); this file is the short,
release-oriented summary. The project is pre-release: breaking changes are allowed.

## [Unreleased] - 2026-11-18

### Security / reliability
- Local rate-limit fallback is bounded (monotonic clock, per-key window, sweep, 10,000-key cap) (audit M-04).
- `/health` reports `rate_limit: fail_closed` in staging/production when Redis is down (M-11).

### Payments
- **Breaking (schema):** new `refund_operations` table in the baseline migration; recreate development databases.
- Gateway refunds are a durable three-phase workflow with idempotency, lease and state machine; the gateway is never called
  inside a locked transaction (M-10).
- `refund_recovery_job` finishes interrupted refunds without a second gateway call; unknown gateway outcomes go to
  `manual_review`; manual-card refunds answer `409 REFUND_NOT_SUPPORTED` instead of a 500 (M-03).

### CI / tooling
- Web E2E (Playwright) is a blocking CI job (M-05).
- `npm audit`: runtime dependencies block at `high`, dev tooling at `critical` while picomatch (GHSA-fc5q-39xc-vjpf) has no
  patched release (ADR-R2).
- `scripts/gen_docs.py` fails with an explicit "install the API dependencies" message instead of a bare ImportError (M-02).

### Verification
- PostgreSQL lane incl. real-lock refund concurrency test, Compose stack from an empty DB and `scripts/e2e_smoke.py` pass on a real host (details in docs/06).
- `deploy.yml` diagnoses SSH/secret problems before the deploy step instead of a bare exit 255 (M-09).

### Docs
- ADR-R1 (open business decisions: refund, commission, FX, identity), refund workflow in docs/15, regenerated `docs/STATUS.md`.
