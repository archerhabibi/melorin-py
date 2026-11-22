# BASELINE-REPORT (Phase 0)

- Date: 2026-11-22/23 · Orchestrator: AI-00
- Base: `main` @ `ee384d60ba89fa25b13a694545fc26b62e7ae14a` (clean checkout, no code changes made during baseline; `git status --porcelain` empty afterwards)
- Environment: test server `melorin-server` — Ubuntu 24.04.5, 2 vCPU, 3.8 GB RAM, Python 3.12.3, Node 22.23, Docker, PostgreSQL 16 and Redis 7 in containers (127.0.0.1 only). Stack installed per `requirements-dev.txt` with `--require-hashes`.

## Result
Every CI step that could be reproduced on the server passed on the untouched base commit (details and numbers in `TEST-BASELINE.md`). **The baseline is green; there are no pre-existing failures to subtract from team PRs.** Any red result in a team PR is therefore attributable to that PR.

## What the repository is
Mature pre-release modular monolith (~48k LOC Python backend, 82 tables, 440 API operations, 2 React apps, 2 bots, worker, compose stack). It has had at least 21 audit/remediation rounds (`docs/06`, branches `refactor/audit-r12…r21`, `docs/audits/2026-11-19-deep-technical-audit.fa.md`). Consequences for this program:
1. Cheap findings are likely already gone. Teams must look for what automated guards (`check_g001_g010`, import-linter, ruff, mypy scope, coverage floors) do **not** cover.
2. Documents in `docs/` contain claims such as "unverified" integration evidence (AUD-006). Teams must treat doc claims as hypotheses.
3. AUD-001/002/003/007/008 were fixed by merged branches; do not re-report without re-verification.

## Candidate observations from Phase 0 (NOT findings; to be confirmed by owners)
| ID | Observation | Owner to check |
|---|---|---|
| OBS-001 | `hypothesis` is not installed by `requirements-dev.txt`, so `tests/service/test_wallet_properties_db.py` is skipped in CI (property tests on wallet never run). | AI-08 / AI-03 |
| OBS-002 | `tests/postgres/test_migration_baseline.py` (2 tests) skipped without `TEST_PG_ADMIN_URL`; CI `postgres-lane` sets only `TEST_PG_URL`. Verify whether the baseline migration test runs anywhere in CI. | AI-08 / AI-07 |
| OBS-003 | `tests/contracts/test_order_idempotency_contract.py` skipped: "requires the live PostgreSQL/Redis integration fixture" even when both are available. | AI-08 / AI-03 |
| OBS-004 | Branch protection requires only the `quality` check; `web-e2e` and `postgres-lane` are not required checks. | AI-07 |
| OBS-005 | Merge commits allowed together with squash/rebase; `delete_branch_on_merge` is off; 107 remote branches, 50 unmerged. | AI-00 / AI-07 |
| OBS-006 | 31 open PRs (30 Dependabot): major bumps (eslint 10, SQLAlchemy 2.1, node 26, python 3.15 images, GitHub Actions majors) need compatibility review, not blind merge. | AI-07 |
| OBS-007 | CI action pins in `ci.yml` are SHA-pinned; Dependabot is raising actions bumps — verify the policy stays SHA-pinned. | AI-07 |
| OBS-008 | `docs/audits/...` documents deploy failure at the SSH pre-check (AUD-005) and unverified provider evidence (AUD-006): no real provider sandbox evidence exists. | AI-04 / AI-07 |

## Limits of this baseline
- No real third-party provider (Zarinpal, Sanaei, PasarGuard, Telegram, S3, Google) was contacted; only mocks/fakes are exercised.
- The full compose stack and the restore drill were not run in Phase 0 (assigned to AI-07/AI-08).
- Load probe was not run in Phase 0.
