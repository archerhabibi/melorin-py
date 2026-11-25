# TEST-BASELINE (Phase 0)

Base `ee384d60ba89fa25b13a694545fc26b62e7ae14a`, untouched checkout, test server (2 vCPU / 3.8 GB, Ubuntu 24.04, Python 3.12.3, Node 22.23, PG 16, Redis 7). Commands mirror `.github/workflows/ci.yml`. Logs are kept on the server in `/work/baseline/`.

## Backend / Python
| Command | Result | Notes |
|---|---|---|
| `lint-imports` | PASS | |
| `ruff check melorin` | PASS | |
| `ruff format --check melorin tests alembic` | PASS | |
| `mypy --config-file pyproject.toml` | PASS | 25 s |
| `python -m compileall -q melorin` | PASS | |
| `pytest -n 2 -m "not integration" --cov=melorin --cov-fail-under=75` on PostgreSQL URL | PASS | 2893 passed, 12 skipped, 574 s, coverage 88.65 % (threshold 75 %) |
| `scripts/check_coverage_floors.py coverage.xml` | PASS | domain 97.9 % (floor 92), wallet 94.5 (88), payments 90.1 (85), orders 93.4 (88), uow 100 (90) |
| `pytest -n 2 -m "not integration" tests/http tests/service` (SQLite default) | PASS | 127 s |
| `pytest -m integration` (PG + Redis, mock providers) | PASS | 2 passed, **4 skipped** (see OBS-001..003), 11 s |
| `pytest ../telegram-main/tests` | PASS | |
| `pytest ../telegram-reseller/tests` | PASS | |
| `TEST_PG_URL=... pytest -n 2 -m "not integration"` (CI `postgres-lane`) | PASS | 2903 passed, **2 skipped**, 1624 s on this 2-vCPU host |

## Static guards and supply chain
| Command | Result |
|---|---|
| `verify_runtime.py`, `check_frontend_contracts.py`, `check_release_matrix.py`, `check_g001_g010.py`, `check_quality_config.py`, `check_ops_p0.py` | PASS (each) |
| `gen_api_client.py --check`, `gen_docs.py --check` (440 operations, head `0001_initial_baseline`) | PASS |
| `scripts/check_secrets.sh` | PASS |
| `pip-audit -r requirements.txt`, `pip-audit -r requirements-dev.txt` | PASS (no known vulnerabilities reported by pip-audit 2.10.1 at run time) |
| `scripts/lock_requirements.sh --check` | PASS |
| `scripts/test_deploy.sh`, `scripts/test_restore_drill.sh` | PASS (offline script tests) |

## Frontend
| App | install | audit rt/dev | lint | typecheck | format | unit tests | build |
|---|---|---|---|---|---|---|---|
| store-web | PASS | PASS / PASS | PASS | PASS | PASS | PASS 86 tests / 15 files | PASS |
| admin-web | PASS | PASS / PASS | PASS | PASS | PASS | PASS 361 tests / 47 files | PASS |
| web-kit | PASS | audit PASS | | | | | |
| api-client | PASS | | | `generate` + typecheck PASS | | PASS | |

`check_bundle_budget.py` PASS · `check_web_lockfiles.py` PASS · Playwright E2E (`e2e/`, Chromium): **24 passed, 2 skipped** (66 s).

## Not run in Phase 0
- `alembic upgrade head && alembic check` on an empty DB, `migration_smoke.sh`, full stack start + `e2e_smoke.py` + `load_probe.py`, Docker image builds, compose `config -q`, restore drill with real data. Assigned to AI-03 / AI-07 / AI-08 in their audits.

## Skips to be explained (owners: AI-08, AI-03)
- `tests/service/test_wallet_properties_db.py`: `hypothesis` not installed in the CI dev lock.
- `tests/postgres/test_migration_baseline.py` x2: `TEST_PG_ADMIN_URL` not set.
- `tests/contracts/test_order_idempotency_contract.py`: marked as requiring a live integration fixture.
- Playwright: 2 skipped specs.

## Variance note
Wall-clock times are specific to this 2-vCPU host and are not a performance baseline for the product.
