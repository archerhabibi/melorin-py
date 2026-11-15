# r21 full test run (2026-11-15, Ubuntu 24.04, Docker, Chromium)

| Lane | Result |
|---|---|
| lint-imports / ruff / mypy (371 files) | clean, 8 contracts kept |
| API unit suite | 2728 passed, 1 skipped |
| admin-web tsc, eslint, vitest | clean, 309 passed |
| Playwright (Chromium, mocked API) | 24 passed, 2 skipped (need a seeded staging stack) |
| Docker: rebuild + upgrade of an existing r15 database to head 0056 | all services healthy |
| Live smoke scripts/e2e_smoke.py (API + worker + Postgres + Redis, mock panel) | ALL PASSED (32 checks) |
| PostgreSQL 16 lane (TEST_PG_URL) | 8 passed |
| integration + concurrency (PG 16 + Redis 7) | 11 passed, 1 skipped |
| alembic upgrade head from empty, alembic check | head 0056, no drift |
| test_deploy.sh, test_restore_drill.sh | passed |

## Findings
- Alertmanager restart loop (permission denied on the entrypoint bind mount) when the checkout dir and infra/ are mode 0700. Environment issue, fixed with chmod 755 on the checkout and infra/. No code defect.
- No code defects found by any lane.

## Not run
Real PasarGuard panel, real Telegram bots, Zarinpal, Caddy TLS profile, real backup restore with age, the 2 seeded-stack Playwright tests.
