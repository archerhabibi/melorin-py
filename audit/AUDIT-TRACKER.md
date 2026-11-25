# AUDIT-TRACKER

## Decisions
| Date | Decision | By |
|---|---|---|
| 2026-11-22 | Project is unreleased with no users: breaking changes and redesign are allowed; the single Alembic baseline may be regenerated. | Owner |
| 2026-11-22 | The dedicated test server `melorin-server` may be used freely (installs, docker, browsers). | Owner |
| 2026-11-22 | Branch chain kept as proposed; audit phase parallel and read-only, fix phase in chain order. | AI-00 |
| 2026-11-23 | Baseline on `ee384d6` is green on every reproducible CI step. | AI-00 |
| 2026-11-23 | Fix phase runs team by team in chain order and every team is pushed as soon as its first proven change is green (owner request). The test server has no GitHub credentials: commits are relayed through the owner machine over SSH with a pinned host key. | AI-00 |
| 2026-11-23 | AI-05 uses audit/05-frontend-fe001 from the AI-04 head; the pre-existing audit/05-frontend placeholder is preserved. Later branches follow the actual AI-05 PR head. | AI-00 |
| 2026-11-24 | A newly confirmed reseller wallet API issue is fixed in a follow-up stacked on the current AI-05 head; its PostgreSQL concurrency test is included with the API change. | AI-00 |
| 2026-11-24 | The AI-05 follow-ups #166 and #167 forked before the current #165 head and are not ancestors of #173. PR #166 was reconciled with #165; #167 still fails the bundle budget and needs integration into the later stack. | AI-00 |
| 2026-11-24 | PR #167 was reconciled, brought back under the bundle budget, and incorporated after PR #174 in a separate integration branch. Earlier PRs retain their existing bases. | AI-00 |
| 2026-11-24 | BE-005 follows the integrated PR #175 head; it records checkout request identity in the existing pricing snapshot and rejects unverifiable legacy retries. | AI-00 |
| 2026-11-24 | SEC-002 follows the BE-005 branch; password worker slots are retained until the underlying thread finishes, including after cancellation. | AI-00 |
| 2026-11-24 | SEC-003 follows SEC-002; password login rechecks the verified credential and account state under a row lock before issuing a session. | AI-00 |
| 2026-11-24 | SEC-004 follows SEC-003; admin password changes and identity unlinking recheck password proof under a row lock. | AI-00 |
| 2026-11-24 | BE-006 follows PR #179; loyalty redemption retries are rechecked under the existing account lock and conflicting rewards are rejected. | AI-00 |
| 2026-11-24 | BE-007 follows PR #180; loyalty adjustment retries verify the existing amount and operation kind. | AI-00 |
| 2026-11-24 | BE-008 follows PR #181; both reward engines serialize with refunds and reject late completions of refunded orders. | AI-00 |
| 2026-11-24 | BE-009 follows PR #182; a replayed first purchase cannot earn a second referral commission. | AI-00 |
| 2026-11-24 | QA-004 follows PR #183; storefront tests wait for pending storage work and wallet notifications before continuing. | AI-00 |
| 2026-11-24 | BE-010 and BE-011 follow PR #184; refunding an offset reward restores debt and settlement/refund use the same lock order. | AI-00 |
| 2026-11-24 | INT-003 follows PR #185; OCR connections use a validated address while retaining the provider hostname for TLS. | AI-00 |
| 2026-11-24 | SEC-005 follows PR #186; reseller domain proof connects to a checked address and preserves the hostname for TLS. | AI-00 |
| 2026-11-24 | INT-004 follows PR #187; PasarGuard password sessions are tied to the credentials that obtained them and explicit access tokens are used as supplied. | AI-00 |
| 2026-11-24 | DB-004 and DB-005 follow PR #188; bank SMS matching compares pending and provisional receipts together and serializes decisions with human actions. | AI-00 |
| 2026-11-25 | DB-006 follows PR #189; receipt uploads recheck the payment under the same row lock as review decisions. | AI-00 |
| 2026-11-25 | INT-005 follows PR #190; rejected receipt uploads clean up stored objects when no commit was attempted. | AI-00 |
| 2026-11-25 | INT-006 follows PR #191; cancelled and timed-out OCR processes are terminated and reaped before their slot is released. | AI-00 |
| 2026-11-25 | INT-007 follows PR #192; recheck pending and completed upstream-bot purchases under the chat lock before confirming. | AI-00 |
| 2026-11-25 | INT-008 follows PR #193; chat locks fail closed on Redis errors and release only their own lease. | AI-00 |
| 2026-11-25 | INT-009 follows PR #194; shared purchase state failures stop paid bot flows before confirmation. | AI-00 |
| 2026-11-25 | BE-012 preserves completed reseller wallet retries after the manual adjustment cap is lowered. | AI-00 |
| 2026-11-25 | DB-007 follows PR #196; ledger reversals use the active wallet after account consolidation. | AI-00 |
| 2026-11-25 | OPS-002 follows PR #197; restore drills isolate temporary resources and only drop databases they created. | AI-00 |
| 2026-11-25 | OPS-003 follows PR #198; backup retention is limited to each job's own top-level encrypted archives and checksums. | AI-00 |
| 2026-11-25 | INT-010 follows PR #199; active bot chats renew their Redis lease and stop when ownership is lost. | AI-00 |

## Status
| Team | Phase | State |
|---|---|---|
| AI-00 | 0 | Baseline docs written; PR `audit/00-baseline` |
| AI-01 | 3 | BE-001 fixed (PR #161); BE-002 through BE-012 fixed in follow-ups; broader business-logic review continues |
| AI-02 | 3 | SEC-001 through SEC-005 fixed; authorization matrix test added; 9 `PENDING` bounds closed; broader security review continues |
| AI-03 | 3 | DB-001..DB-007 fixed; order, bank-SMS and consolidation/refund concurrency tested; broader ledger reconciliation and CHECK constraints still to review |
| AI-04 | 3 | INT-001..INT-010 fixed; panel adapters and the rest of bank SMS still to review |
| AI-05 | 3 | FE-001..FE-008 addressed; the reconciled recovery and atomic retry follow-ups are included in the integration branch; frontend audit continues |
| AI-06 | 3 | WRK-001 fixed; worker and bot review continues |
| AI-07 | 3 | OPS-001 through OPS-003 fixed; CI and operations review continues |
| AI-08 | 3 | QA-001..QA-004 fixed; broader test strategy, integration and performance review continues |

## Scope / ownership exceptions
- 2026-11-23 AI-05 added a storefront test dependency and changed the corresponding lockfile (AI-07), and extended browser regression tests (AI-08). AI-07 and AI-08 review these changes during their audits.
- 2026-11-23 AI-02 changed `apps/api/melorin/core/config.py` (AI-01) and `.env.example` (AI-07), one default each, for SEC-001. Approved by AI-00; the owners review them in the AI-02 PR.
- 2026-11-24 BE-002 updates the shared PostgreSQL concurrency test (AI-08) alongside the reseller API fix (AI-01).
- 2026-11-24 BE-003 replaces the skipped order concurrency contract (AI-08) alongside the order service fix (AI-01).
- 2026-11-24 BE-006 adds a PostgreSQL concurrency regression (AI-08) alongside the loyalty API fix (AI-01).
- 2026-11-24 BE-007 adds a PostgreSQL concurrency regression (AI-08) alongside the loyalty API fix (AI-01).
- 2026-11-24 BE-008 adds a PostgreSQL concurrency regression (AI-08) for reward and refund ordering (AI-01, AI-03, AI-06).
- 2026-11-24 BE-009 adds PostgreSQL worker replay coverage (AI-08) for referral settlement (AI-01, AI-03, AI-06).
- 2026-11-24 QA-004 updates shared storefront test setup and asynchronous wallet assertions (AI-08, AI-05).
- 2026-11-24 BE-010 and BE-011 add PostgreSQL refund and settlement races (AI-08) for referral finance (AI-01, AI-03, AI-06).
- 2026-11-24 INT-003 adds TLS and endpoint-policy regression coverage (AI-08) alongside the OCR integration fix (AI-04).
- 2026-11-24 SEC-005 updates reseller domain verification and its HTTP policy description (AI-01) and adds security regressions (AI-08).
- 2026-11-24 DB-004 and DB-005 update bank-SMS matching (AI-04) and add HTTP and PostgreSQL concurrency regressions (AI-08).
- 2026-11-25 DB-006 adds PostgreSQL receipt upload and payment decision races (AI-08) alongside the payment service fix (AI-03).
- 2026-11-25 INT-005 changes receipt upload cleanup (AI-03) and adds storage and HTTP tests (AI-08).
- 2026-11-25 INT-006 adds subprocess cancellation tests (AI-08) alongside the OCR integration fix (AI-04).
- 2026-11-25 INT-007 changes purchase idempotency and recovery in the upstream-bot integration and adds concurrency tests (AI-08).
- 2026-11-25 INT-008 adds upstream-bot lock failure and cancellation regressions (AI-08).
- 2026-11-25 INT-009 adds shared purchase state and fake-provider failure regressions (AI-08).
- 2026-11-25 BE-012 adds a PostgreSQL concurrency regression (AI-08) alongside the reseller wallet change (AI-01).
- 2026-11-25 DB-007 adds account-linking and PostgreSQL race tests (AI-02/AI-08) alongside the ledger change (AI-03).

- 2026-11-25 INT-010 adds lease-loss and cancellation regressions (AI-08) alongside the upstream-bot integration fix (AI-04).
