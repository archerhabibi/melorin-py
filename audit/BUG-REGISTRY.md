# BUG-REGISTRY

IDs: `<TEAM>-NNN` (BE, SEC, DB, INT, FE, WRK, OPS, QA). Status: Open / Confirmed / In Progress / Fixed / Verified / Deferred / Rejected.
Full finding records live in `audit/reports/<team>/REPORT.md`; this table is the index maintained by AI-00.

| ID | Severity | Title | Team | Status | Report |
|---|---|---|---|---|---|
| BE-001 | Low | Unbounded client integers (query, path, body, list items) reach a DB bind or arithmetic and answer HTTP 500 | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |

## Pre-existing, already fixed on `main` (do not re-report without re-verifying)
AUD-001 payment intent retry, AUD-002 refund availability, AUD-003 Zarinpal refund credentials UI, AUD-007 worker lock fail-open, AUD-008 worker metrics scrape (`docs/audits/2026-11-19-deep-technical-audit.fa.md`; fixing branches are ancestors of `main`).
