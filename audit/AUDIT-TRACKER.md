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

## Status
| Team | Phase | State |
|---|---|---|
| AI-00 | 0 | Baseline docs written; PR `audit/00-baseline` |
| AI-01 | 3 | BE-001 fixed (PR #161); BE-002 fixed in a follow-up on the AI-05 head |
| AI-02 | 3 | SEC-001 fixed, authorization matrix test added; 9 `PENDING` bounds closed |
| AI-03 | 3 | DB-001..DB-003 fixed; ledger reconciliation, CHECK constraints and the order-creation concurrency test follow |
| AI-04 | 3 | INT-001 (SMTP certificate verification) and INT-002 (webhook response bounds) fixed; panel adapters and the rest of bank SMS still to review |
| AI-05 | 3 | FE-001..FE-008 addressed; recovery follow-up reconciled with PR #165; frontend audit continues |
| AI-06..AI-08 | 1 | Not started (sequential, in chain order) |

## Scope / ownership exceptions
- 2026-11-23 AI-02 changed `apps/api/melorin/core/config.py` (AI-01) and `.env.example` (AI-07), one default each, for SEC-001. Approved by AI-00; the owners review them in the AI-02 PR.
- 2026-11-24 BE-002 updates the shared PostgreSQL concurrency test (AI-08) alongside the reseller API fix (AI-01).
