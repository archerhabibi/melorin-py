# Melorin - Generated Status

> **Machine-owned file.** Regenerate with `python scripts/gen_docs.py`; CI fails (`--check`) if the
> migration head or API surface below is stale. Release approval is **not** stated here - the only
> release-status source is `docs/RELEASE-EVIDENCE-MATRIX.md`.

| Measurement | Value |
|---|---|
| Alembic head | `0031_event_center_health` |
| Migrations | 31 |
| ORM tables | 56 |
| API operations | 229 |
| API paths | 196 |
| Test files / test functions (static count) | 145 / 1236 |
| Coverage | not measured here (CI writes `apps/api/coverage.xml`; run `pytest --cov=melorin --cov-report=xml`) |
| Documents: repo root / `docs/` / `docs/history/` (tests only) | 3 / 29 / 4 |

Where things live: requirements and design `docs/01`-`docs/17` (13-17 are design records; 12 and 15 were merged into `DECISIONS.md` and `14`); route list `docs/API.md`;
operations `docs/RUNBOOK.md`; decisions `docs/DECISIONS.md`; change log `docs/CHANGE_LOG.md`;
historical phase reports (evidence, never current status) in git tag `docs-history-2026-10-22`, indexed in `docs/HISTORY.md`.
