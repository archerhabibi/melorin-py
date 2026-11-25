# DEPENDENCY-MAP (Phase 0)

## Enforced Python layering
Source: `apps/api/pyproject.toml [tool.importlinter]`; `lint-imports` = PASS at baseline.

- `domain` imports nothing of ours. `kernel` is the bottom layer. `core` imports only kernel + domain. `channels` never import admin / reseller / reports / worker / app / cli.
- Feature module stack (a layer may import only layers below it), top to bottom:
  1. `admin`
  2. `reports`
  3. `reseller`
  4. `orders | payments | identity`
  5. `panelops`
  6. `catalog | referral | loyalty | tickets`
  7. `vpn_accounts | wallet | webhooks | notifications | eventcenter | broadcast`
  8. `panel_integrations`
- Also: `catalog.allocation` is a one-way stack (offers, routing, sale|reseller_prices); `panelops` reaches `vpn_accounts` only through lifecycle ports; `admin` must not build panel adapters/sessions directly.

## Cross-unit contracts (change in one means update the other)
| Contract | Producer | Consumers | Guard |
|---|---|---|---|
| OpenAPI snapshot `packages/api-client/openapi.json` + generated types | API routers/schemas | api-client, admin-web, store-web | `gen_api_client.py --check`; `npm run generate && git diff --exit-code` |
| `docs/STATUS.md`, `docs/API.md` (generated) | routes, models, migrations | docs | `gen_docs.py --check` |
| Alembic baseline | `kernel/models` | DB tests, installer, `alembic check` | CI `alembic upgrade head && alembic check`, `migration_smoke.sh` |
| Core HTTP API | api | telegram-main, telegram-reseller (HTTP only, no DB) | bot tests with `MELORIN_CORE_URL=http://core.invalid` |
| Worker jobs and outbox | modules/* enqueue | `worker/*` | `tests/service`, `scripts/postgres_concurrency_smoke.py` |
| Compose and scripts | `docker-compose*.yml`, `.env.example` | `scripts/*`, `check_ops_p0.py`, `integration_smoke.sh` | CI compose `config -q`, guards |
| Dependency locks | `requirements*.in`, `package.json` | `requirements*.txt` (hash-locked), `package-lock.json` | `lock_requirements.sh --check`, `check_web_lockfiles.py` |

## Build-order dependencies between teams
DB schema (AI-03) -> API/backend (AI-01) -> OpenAPI snapshot -> frontends (AI-05) and bots (AI-06).
Security (AI-02) crosses core, identity and frontends. Integrations (AI-04) sits on payments/panel adapters, which touch DB and Worker. DevOps (AI-07) owns CI/compose. QA (AI-08) consumes everything.

## Merge-conflict hotspots (generated / shared files)
`packages/api-client/openapi.json` and generated types, `docs/STATUS.md`, `docs/API.md`, `apps/api/alembic/versions/0001_initial_baseline.py`, `CHANGELOG.md`, `docs/06-ARCHITECTURE-DECISIONS.md`, `package-lock.json` files, `requirements*.txt`, `apps/api/pyproject.toml`.

Rules:
- Generated files are regenerated on rebase, never hand-merged. Only the owner of the changed area commits them.
- Lock files are touched only by AI-07, unless a dependency change was approved.
- Since the project is unreleased, the single baseline migration may be edited/regenerated instead of stacking migrations. This is an AI-03 decision and must be logged in `AUDIT-TRACKER.md`.
