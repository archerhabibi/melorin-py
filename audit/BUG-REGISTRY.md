# BUG-REGISTRY

IDs: `<TEAM>-NNN` (BE, SEC, DB, INT, FE, WRK, OPS, QA). Status: Open / Confirmed / In Progress / Fixed / Verified / Deferred / Rejected.
Full finding records live in `audit/reports/<team>/REPORT.md`; this table is the index maintained by AI-00.

| ID | Severity | Title | Team | Status | Report |
|---|---|---|---|---|---|
| BE-001 | Low | Unbounded client integers (query, path, body, list items) reach a DB bind or arithmetic and answer HTTP 500 | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-002 | High | Reseller wallet retries can be rejected after a successful debit or falsely acknowledge a different adjustment | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-003 | Medium | Concurrent retries of a renewal can report an error after the original order succeeded | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| SEC-001 | Low | Per-key API rate limit is stored and shown to the reseller but not enforced by default | AI-02 | Fixed | audit/reports/security/REPORT.md |
| DB-001 | Low | Foreign keys the code filters on (`vpn_accounts.panel_id`, `orders.vpn_account_id`, `payments.receipt_file_id`) have no index | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| DB-002 | Low | Ledger tables are "append-only" by convention only; the database accepts UPDATE/DELETE | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| DB-003 | Low | A ledger transaction can be reversed twice when the second caller uses another idempotency key | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| INT-001 | Medium | SMTP over TLS (`ssl` and `starttls`) accepts any certificate and any host name: `smtplib` falls back to an unverified context | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-002 | Medium | Outgoing webhook delivery buffers the receiver's whole response and bounds only each read: a tenant-controlled endpoint can exhaust worker memory or hold its delivery slots | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| FE-001 | Medium | Direct web deployments omit CSP and opener policy; asset locations suppress inherited security headers | AI-05 | Fixed | audit/reports/frontend/REPORT.md |
| FE-002 | Medium | A rendering exception unmounts the storefront without a recovery screen | AI-05 | Fixed | audit/reports/frontend/REPORT.md |
| FE-003 | High | Wallet topup retry state is shared between accounts using the same store and browser | AI-05 | Fixed | audit/reports/frontend/REPORT.md |
| FE-004 | High | Retrying a purchase or renewal after a lost response uses a new idempotency key | AI-05 | Fixed | audit/reports/frontend/REPORT.md |
| FE-005 | High | Concurrent order attempts can use different keys or erase a newer pending key across tabs | AI-05 | Fixed | audit/reports/frontend/REPORT.md |
| FE-006 | High | Unresolved purchases and renewals cannot be recovered when a fresh quote or renewal eligibility fails | AI-05 | Fixed | audit/reports/frontend/REPORT.md |
| FE-007 | High | Concurrent or delayed wallet topup responses and receipts can overwrite a newer retry key | AI-05 | Fixed | audit/reports/frontend/REPORT.md |
| FE-008 | High | Loyalty reward retries can spend points twice after an ambiguous response or reload | AI-05 | Fixed | audit/reports/frontend/REPORT.md |
| WRK-001 | Medium | Outbox database errors can leave events leased without retry accounting or commit partial work | AI-06 | Fixed | audit/reports/telegram-workers/REPORT.md |
| OPS-001 | Medium | CI skips the empty-database migration and ledger immutability integration tests | AI-07 | Fixed | audit/reports/devops/REPORT.md |
| QA-001 | Medium | Random six-character order numbers can collide and make PostgreSQL tests flaky | AI-08 | Fixed | audit/reports/qa-performance/REPORT.md |
| QA-002 | Medium | PostgreSQL wallet property test silently skips because Hypothesis is missing from CI dependencies | AI-08 | Fixed | audit/reports/qa-performance/REPORT.md |
| QA-003 | Medium | Order idempotency concurrency contract is always skipped | AI-08 | Fixed | audit/reports/qa-performance/REPORT.md |

## Pre-existing, already fixed on `main` (do not re-report without re-verifying)
AUD-001 payment intent retry, AUD-002 refund availability, AUD-003 Zarinpal refund credentials UI, AUD-007 worker lock fail-open, AUD-008 worker metrics scrape (`docs/audits/2026-11-19-deep-technical-audit.fa.md`; fixing branches are ancestors of `main`).
