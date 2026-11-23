# BUG-REGISTRY

IDs: `<TEAM>-NNN` (BE, SEC, DB, INT, FE, WRK, OPS, QA). Status: Open / Confirmed / In Progress / Fixed / Verified / Deferred / Rejected.
Full finding records live in `audit/reports/<team>/REPORT.md`; this table is the index maintained by AI-00.

| ID | Severity | Title | Team | Status | Report |
|---|---|---|---|---|---|
| BE-001 | Low | Unbounded client integers (query, path, body, list items) reach a DB bind or arithmetic and answer HTTP 500 | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| SEC-001 | Low | Per-key API rate limit is stored and shown to the reseller but not enforced by default | AI-02 | Fixed | audit/reports/security/REPORT.md |
| DB-001 | Low | Foreign keys the code filters on (`vpn_accounts.panel_id`, `orders.vpn_account_id`, `payments.receipt_file_id`) have no index | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| DB-002 | Low | Ledger tables are "append-only" by convention only; the database accepts UPDATE/DELETE | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| DB-003 | Low | A ledger transaction can be reversed twice when the second caller uses another idempotency key | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| INT-001 | Medium | SMTP over TLS (`ssl` and `starttls`) accepts any certificate and any host name: `smtplib` falls back to an unverified context | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| QA-001 | Medium | Flaky `tests/http/test_store_scoped_referral_program.py::test_earned_counts_every_commission_of_the_store_not_only_the_latest_page_the_screens_list` (IntegrityError on PostgreSQL, CI run 45077001718) | AI-08 | Open | (AI-08 report) |

## Pre-existing, already fixed on `main` (do not re-report without re-verifying)
AUD-001 payment intent retry, AUD-002 refund availability, AUD-003 Zarinpal refund credentials UI, AUD-007 worker lock fail-open, AUD-008 worker metrics scrape (`docs/audits/2026-11-19-deep-technical-audit.fa.md`; fixing branches are ancestors of `main`).
