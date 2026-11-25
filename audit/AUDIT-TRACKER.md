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

## Status
| Team | Phase | State |
|---|---|---|
| AI-00 | 0 | Baseline docs written; PR `audit/00-baseline` |
| AI-01 | 3 | BE-001 fixed (PR #161); BE-002 through BE-005 fixed in follow-ups; broader business-logic review continues |
| AI-02 | 3 | SEC-001 through SEC-003 fixed; authorization matrix test added; 9 `PENDING` bounds closed; broader security review continues |
| AI-03 | 3 | DB-001..DB-003 fixed; order-creation concurrency now tested, ledger reconciliation and CHECK constraints still to review |
| AI-04 | 3 | INT-001 (SMTP certificate verification) and INT-002 (webhook response bounds) fixed; panel adapters and the rest of bank SMS still to review |
| AI-05 | 3 | FE-001..FE-008 addressed; the reconciled recovery and atomic retry follow-ups are included in the integration branch; frontend audit continues |
| AI-06 | 3 | WRK-001 fixed; worker and bot review continues |
| AI-07 | 3 | OPS-001 fixed; CI and operations review continues |
| AI-08 | 3 | QA-001..QA-003 fixed; broader test strategy, integration and performance review continues |

## Scope / ownership exceptions
- 2026-11-23 AI-05 added a storefront test dependency and changed the corresponding lockfile (AI-07), and extended browser regression tests (AI-08). AI-07 and AI-08 review these changes during their audits.
- 2026-11-23 AI-02 changed `apps/api/melorin/core/config.py` (AI-01) and `.env.example` (AI-07), one default each, for SEC-001. Approved by AI-00; the owners review them in the AI-02 PR.
- 2026-11-24 BE-002 updates the shared PostgreSQL concurrency test (AI-08) alongside the reseller API fix (AI-01).
- 2026-11-24 BE-003 replaces the skipped order concurrency contract (AI-08) alongside the order service fix (AI-01).
