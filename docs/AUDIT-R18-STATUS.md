# Melorin: architecture audit status (r18)

**Branch:** `refactor/audit-r18-impl` (on top of r17, merge commit `4aa0cdd`)
**Replaces as the live reference:** `docs/AUDIT-2026-11-15.md` (kept as a historical report; its findings are mapped to decisions in the table below).

## 1. What r18 changed

| Area | Change |
|---|---|
| Admin menu | «تیکت‌ها» moved from «فروش و عملیات» to the renamed group «اعلان‌ها، ارتباطات و پشتیبانی» (broadcast, event center, tickets). UI grouping only: tickets, notifications and the event center remain separate backend modules. Still 8 groups. |
| Menu tests | `nav-structure.test.js` pins the group, `nav-role-matrix.test.js` pins what owner / manager / finance / support / viewer see. |
| Payments | `payments/bank_sms.py` (654 lines) is now the package `payments/bank_sms/` (`config`, `authentication`, `matching`, `reconciliation`, `ingestion`, `review`). Every old name is still importable from `melorin.modules.payments.bank_sms`. No behaviour change. |
| Loyalty | `loyalty/service.py` (777 lines) is split into `common`, `tiers`, `program`, `rewards`, `ledger`, `earning`, `redemption`, `adjustments`, `summary`. `service.py` stays the facade the worker and tests patch. |
| Referral | `referral/service.py` (480) split into `attach`, `commissions`, `rules`; facade kept. |
| Reports | `reports/analytics.py` (509) split into `analytics_compute` (pure computation), `analytics_queries` (DB reads) and the facade (`build_analytics`, CSV). |
| Dead code | 14 unreferenced backend functions / schemas and 3 unreferenced admin-web exports removed (list in the commit). Vulture at 80% confidence reports nothing. |
| Admin web layout | `apps/admin-web/src` is now `app/` (shell, nav, routes, access), `api/` and `features/<feature>/`. Pure moves; `kit*`, `ui`, `dataKit`, `charts`, `theme` stay at the root until a `shared/` pass. Python contract helpers resolve moved files by name (`_source.web_file`). |

## 2. Old audit findings (AUDIT-2026-11-15) and their status

| Finding | Status |
|---|---|
| web-kit lockfile missing | fixed (r13+) |
| 78 `authFetch` uses | typed client migration done; 2 CSV downloads stay on purpose (raw response) |
| mypy scope | whole backend gated |
| legacy router re-exports | removed |
| Telegram buttons group vs `system` permission | kept in «سیستم و امنیت» on purpose (owner only) |
| large Frontend files | feature layout done; the files themselves are still large (see register) |

## 3. Technical debt register (open items only)

| # | Item | Why it stays open |
|---|---|---|
| 1 | `upstream_bot/adapter.py` (543 lines after r19) | r19 moved the defaults (`config.py`) and the mapping store / chat lock (`state.py`) out. The purchase, renewal and refund flows stay in one class on purpose: they are an ordered, stateful bot protocol. |
| 2 | Large admin-web files (`ResellersView`, `PanelsView`, `AdminTeamView`, `UpstreamBotFields`, `TelegramLoginSettings`, `ServerForm`, `infra`, `OrdersView`, `ReportsView`, 530 to 640 lines each) | Moved into feature folders; splitting their bodies is a behaviour-risk change and needs its own pure-move PRs. |
| 3 | ~~`shared/` folder in admin-web~~ | done in r19: `kit*`, `ui`, `dataKit`, `charts`, `palette`, `theme`, `Trend`, `types`, `useDialog` now live in `src/shared/`. |
| 4 | Evidence that needs real systems | real PasarGuard panel, real Telegram bots, Zarinpal, Caddy + Prometheus/Alertmanager profile, Playwright, backup restore drill, upgrade from an older database |
| 5 | Rotate the GitHub token that was pasted into chat | security hygiene, outside the repository |

## 4. Target architecture (unchanged principle)

Modular monolith. Business logic only in `domain`, `kernel` and the owning module; admin web, store web and bots only consume the API. Payments/Wallet, Orders/VPN accounts, PanelOps/Panel integrations, Identity/Reseller, Notifications/Event center/Broadcast, Referral/Loyalty stay separate modules. File splits keep a facade module so callers, workers and test patch points do not move.

## 5. Verification run for r18 (2026-11-15, Ubuntu 24.04, Python 3.12, Node 22)

| Control | Result |
|---|---|
| import-linter | 8 of 8 contracts kept |
| ruff check / format | clean |
| mypy | clean, 369 source files |
| API suite (not integration, not concurrency) | 2730 passed, 11 skipped (two tests were adjusted for the splits: a source-reading contract and one monkeypatch target) |
| admin-web | tsc, eslint, vitest 42 files / 309 tests passed |
| PostgreSQL 16 lane (`TEST_PG_URL`) | 8 passed |
| integration + concurrency markers on PostgreSQL 16 + Redis 7 | 11 passed, 1 skipped |
| alembic upgrade head from an empty database, alembic check | reached head, no drift |
| repo guards (`gen_docs --check`, G001-G010, frontend contracts, quality config, ops P0) | passed |

Not run: real panels, Telegram bots, Zarinpal, Caddy/Prometheus profile, Playwright, backup restore drill, upgrade from an older database.
