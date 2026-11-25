# BUG-REGISTRY

IDs: `<TEAM>-NNN` (BE, SEC, DB, INT, FE, WRK, OPS, QA). Status: Open / Confirmed / In Progress / Fixed / Verified / Deferred / Rejected.
Full finding records live in `audit/reports/<team>/REPORT.md`; this table is the index maintained by AI-00.

| ID | Severity | Title | Team | Status | Report |
|---|---|---|---|---|---|
| BE-001 | Low | Unbounded client integers (query, path, body, list items) reach a DB bind or arithmetic and answer HTTP 500 | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-002 | High | Reseller wallet retries can be rejected after a successful debit or falsely acknowledge a different adjustment | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-003 | Medium | Concurrent retries of a renewal can report an error after the original order succeeded | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-004 | Medium | Concurrent checkout retries can report an exhausted coupon after the original order succeeded | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-005 | Medium | Reusing a checkout key with different order details can falsely acknowledge an earlier purchase | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-006 | Medium | Concurrent loyalty redemption retries can fail or acknowledge a different reward | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-007 | Medium | A loyalty adjustment can acknowledge a different amount for an existing key | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-008 | High | A delayed completion event can award loyalty points and referral cash after an order refund | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-009 | High | Replayed first-purchase events can pay both a signup reward and a commission for the same order | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-010 | High | Refunding an offset referral reward can erase outstanding clawback debt | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-011 | Medium | Referral settlement and refund can deadlock by locking wallet and clawback in opposite order | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| BE-012 | Medium | Lowering the manual adjustment cap makes completed wallet retries fail | AI-01 | Fixed | audit/reports/backend-core/REPORT.md |
| SEC-001 | Low | Per-key API rate limit is stored and shown to the reseller but not enforced by default | AI-02 | Fixed | audit/reports/security/REPORT.md |
| SEC-002 | Medium | Cancelled password operations can exceed the intended KDF concurrency bound | AI-02 | Fixed | audit/reports/security/REPORT.md |
| SEC-003 | High | Password login can succeed with credentials changed during verification | AI-02 | Fixed | audit/reports/security/REPORT.md |
| SEC-004 | High | Stale password proof can overwrite a newer admin password or unlink a login method | AI-02 | Fixed | audit/reports/security/REPORT.md |
| SEC-005 | Medium | Reseller domain proof validated DNS without binding the connection to a checked address | AI-02 | Fixed | audit/reports/security/REPORT.md |
| DB-001 | Low | Foreign keys the code filters on (`vpn_accounts.panel_id`, `orders.vpn_account_id`, `payments.receipt_file_id`) have no index | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| DB-002 | Low | Ledger tables are "append-only" by convention only; the database accepts UPDATE/DELETE | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| DB-003 | Low | A ledger transaction can be reversed twice when the second caller uses another idempotency key | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| DB-004 | High | Bank SMS matching can choose a receipt without comparing open provisional credits and all eligible pending receipts | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| DB-005 | High | A stale bank SMS matcher can reopen a linked message or override a human ignore decision | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| DB-006 | High | A stale receipt upload can overwrite a completed payment decision | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| DB-007 | High | Reversals after account consolidation post to an inaccessible retired wallet | AI-03 | Fixed | audit/reports/database-finance/REPORT.md |
| INT-001 | Medium | SMTP over TLS (`ssl` and `starttls`) accepts any certificate and any host name: `smtplib` falls back to an unverified context | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-002 | Medium | Outgoing webhook delivery buffers the receiver's whole response and bounds only each read: a tenant-controlled endpoint can exhaust worker memory or hold its delivery slots | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-003 | Medium | OCR endpoint validation did not bind the checked address to the connection | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-004 | Medium | PasarGuard can use a cached token for different or missing credentials | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-005 | Medium | Rejected receipt uploads can leave unreferenced stored files | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-006 | Medium | Cancelled receipt OCR can leave a Tesseract child running | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-007 | High | Concurrent or unanswered upstream-bot purchase attempts can confirm a purchase twice | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-008 | High | Upstream-bot chat locks can be bypassed, leaked or delete another owner | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-009 | High | Upstream-bot purchases can proceed after shared state fails or is unreadable | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-010 | High | An expired upstream-bot chat lease can allow overlapping paid flows | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-011 | High | Retried upstream-bot renewals can be charged twice or falsely reconciled | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-012 | High | A stale chat owner can overwrite or delete its successor's purchase state | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
| INT-013 | Medium | An OCR provider can send an unbounded or indefinitely slow response | AI-04 | Fixed | audit/reports/integrations/REPORT.md |
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
| OPS-002 | High | A failed or overlapping restore drill can delete another database or overwrite its dump | AI-07 | Fixed | audit/reports/devops/REPORT.md |
| OPS-003 | High | Backup retention can delete unrelated files and other backup types | AI-07 | Fixed | audit/reports/devops/REPORT.md |
| QA-001 | Medium | Random six-character order numbers can collide and make PostgreSQL tests flaky | AI-08 | Fixed | audit/reports/qa-performance/REPORT.md |
| QA-002 | Medium | PostgreSQL wallet property test silently skips because Hypothesis is missing from CI dependencies | AI-08 | Fixed | audit/reports/qa-performance/REPORT.md |
| QA-003 | Medium | Order idempotency concurrency contract is always skipped | AI-08 | Fixed | audit/reports/qa-performance/REPORT.md |
| QA-004 | Medium | Storefront tests race unfinished storage work and asynchronous wallet notifications | AI-08 | Fixed | audit/reports/qa-performance/REPORT.md |

## Pre-existing, already fixed on `main` (do not re-report without re-verifying)
AUD-001 payment intent retry, AUD-002 refund availability, AUD-003 Zarinpal refund credentials UI, AUD-007 worker lock fail-open, AUD-008 worker metrics scrape (`docs/audits/2026-11-19-deep-technical-audit.fa.md`; fixing branches are ancestors of `main`).
