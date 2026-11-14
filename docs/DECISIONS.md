# Melorin ADR / open decisions

## Decided in V1
- Modular monolith; only Core owns PostgreSQL and business rules.
- PostgreSQL ledger is append-only source of truth; balance is a locked projection.
- Internal transactional outbox, polling worker in V1; broker remains replaceable.
- Sanaei and PasarGuard adapters implement one standard interface.
- Manual card receipt flow ships; online gateway adapter is optional and disabled until configured.
- Admin can manually review/retry/attach/refund; provisioning failure never auto-refunds.
- Iranian Rial is default currency, amounts are integers in smallest canonical unit.

## Must be approved before production
- Exact email authentication provider/SMTP and Google OAuth production settings.
- Final debt-limit boundary, reseller wallet funding/adjustment policy, commission debt policy.
- Referral attribution scope (platform vs store).
- JWT/session policy, Celery/ARQ choice, Caddy/Nginx, Sentry and metrics stack.
- S3-compatible storage, RPO/RTO, backup target and restore-test schedule.
- Telegram Event Center group/topic permissions and bot token ownership.
- Admin account bootstrap and mandatory/optional 2FA policy.

Open decisions are runtime-configurable where safe, but are not silently treated as requirements.

## v1.1 decisions applied (2026-10-09)

_Merged from the former 12-Change-Log-v1.1.md._

تاریخ: 2026-10-09

این نسخه بر اساس پاسخ‌های مالک محصول به سؤالات باز به‌روزرسانی شده است.

### تصمیم‌های اعمال‌شده
- ارز قابل تنظیم به تفکیک Store.
- Reseller باید از قبل عضو/مشتری Main Store باشد.
- مشتری هر Reseller فقط Wallet همان Store را شارژ می‌کند و مقصد پرداخت متعلق به همان Store است.
- تمام خریدها فقط از Wallet همان Store پرداخت می‌شوند؛ پرداخت خارجی فقط شارژ Wallet است.
- Reseller مجاز به شارژ Wallet مشتریان خودش است.
- کمیسیون/پاداش قابل انتخاب برای هر طرح؛ انتساب بر اساس اولین معرف ثبت‌شده.
- اتصال خودکار هویت‌ها در صورت تطبیق ایمیل تأییدشده؛ تعارض‌ها برای بازبینی دستی گزارش می‌شوند.
- تغییر مالک VPN Account توسط Admin غیرمجاز.
- ARQ + Redis برای کارهای پس‌زمینه.
- RPO <= 24 ساعت و RTO <= 8 ساعت.
- Reseller API و Outgoing Webhook در V1 پیاده‌سازی می‌شوند.
- Coupon V1 با محدوده Store/دامنه مجاز، creator roles، محدودیت مصرف، بازه اعتبار، سقف تخفیف، عدم ترکیب پیش‌فرض و اعتبارسنجی مرکزی Core.
- Debt limit با شرط توقف `balance <= -debt_limit`.

### موارد باز باقی‌مانده
در سند `10-Roadmap-Open-Decisions.md` ثبت شده‌اند؛ از جمله درگاه پرداخت، Email Auth، روش تمدید، Reverse Proxy، Storage، Session/JWT، Monitoring stack، بازیافت کمیسیون خرج‌شده، تنظیم گروه‌های تلگرام و سیاست‌های تکمیلی ارز و شارژ دستی.

## T39 / T36 - coverage floors and migration formatting (2026-11-10)
- Money-handling code has its own line-coverage floors enforced by `scripts/check_coverage_floors.py` in CI (domain 92%, wallet 88%, payments 85%, orders 88%, `core/uow.py` 90%), on top of the global 75% net. Measured on 2026-11-10: 97.4 / 93.2 / 91.0 / 93.1 / 100. Raise floors as coverage grows; do not lower one without recording why here.
- `alembic/` is now covered by `ruff format --check` (CI and `make lint`). The 37 migration files were reformatted only; the full non-integration suite (2390 tests, incl. the migration baseline contract) passes unchanged.

## T16 / T65 - panel families kept, as plug-in adapters (2026-11-10)
- Decision: `sanaei`, `pasarguard` and `upstream_bot` all stay. None is removed; each is a provider adapter declared in `modules/panel_integrations/adapters/providers.py` (`ProviderSpec`: label, transport, features, target kinds, adapter path, contract path).
- Adapter classes and each family's `contract.py` (settings/target validation, capacity label, listing warnings) are imported lazily; `upstream_bot` therefore needs Telethon only when a call is made.
- Core code asks `providers.supports(kind, feature)` / `target_kinds(kind)` instead of comparing `panel.kind` with a string. A new family is one `register_provider(...)` call.
- Guarded by `tests/test_provider_adapters.py` (no concrete family is imported outside the adapter layer, except the PasarGuard wire parsers listed in the test).

## T-R10 - `reportsLogic.js` stays in admin-web; branch hygiene (2026-11-10)
- Review of `apps/admin-web/src/reportsLogic.js` (194 lines): it only formats numbers (`fmt*`), maps labels, draws donut/heat geometry and derives percentage shares and insight sentences from figures that Core already returned. It never computes balances, prices, fees or ledger values, so it is presentation logic and stays in the UI.
- Rule going forward: if a report needs a *new* monetary figure (a total, margin, balance), Core's reports module must return it as a field; the browser may only format and compare it. Same rule as the quote's `balance_after` / `shortfall` (T-R10).
- Branch hygiene (T-W16): the 19 remote branches fully merged into `main` were deleted on 2026-11-10; every commit remains reachable from `main`. Unmerged branches were kept for the owner to decide.

## T-R05 / T-R07 / T-R12 / T-R13 / T-R14 / T-R15 - remediation close-out and deferred work (2026-11-10)
- Done: pasarguard test files are named by feature (`admin_api`, `service_db`, `events`, `account_tools`, `capacity`, `bulk_ops`, `ops_governance`, `ops_maturity`, ...) instead of `phaseN`; `test_q02_bot_inquiry` became `test_bot_inquiry`; panel documents live in `docs/panels/`.
- Done: the PostgreSQL lane (`postgres-lane` in `ci.yml`) is a normal required job (no `continue-on-error`); broad `except Exception` handlers are ratcheted by `test_broad_except_exception_count_only_ratchets_down` (ceiling 104, lower it when you narrow one).
- Deferred on purpose, each needs a real Docker host or product input that this remediation did not have:
  - T-R14 backup out of the Worker: moving `backup_job`/`panel_backup_job` into a dedicated ops container changes the compose topology and the restore drill; do it together with a first compose run on a Docker host.
  - T-R13 OpenTelemetry exporter and a CI performance budget: tracing now exists without new dependencies (see "Trace context" below); an exporter needs a collector decision and hash-locked packages. The `load_probe.py` budget needs the full stack.
  - T-R11 remaining: `store-web/App.jsx` still holds the 1,000-line `App` component and the three admin views were split by block, not by feature; keep going one view per PR with the vitest suites as the safety net. Gradual TypeScript is not started.
  - T-W08 ESLint ceilings stay at 13 / 25: each remaining warning is a `react-hooks/exhaustive-deps` case where a blind fix can loop or refetch, so they need a browser check, not a bulk edit.
  - Merging the pasarguard test files into ~6 files: renames are done; physical merging is cosmetic and was left out to keep git history of each suite readable.

## Trace context (T-G06, 2026-11-10)
- `CorrelationMiddleware` honours an inbound W3C `traceparent` (or creates a trace id), echoes `traceparent` on the response, and every JSON log line carries `trace_id`. `core/http.outbound_client` forwards the same trace id to peers. No SDK, collector or new dependency; `traceparent` is in the CORS allow-list. Tests: `tests/unit/test_tracing.py`.

## T-R11 first split (2026-11-10)
- `store-web/App.jsx`: static copy, constants, `Logo` and `HeroVisual` moved to `landing.jsx`.
- `admin-web`: `TicketsView` -> `ticketsShared.jsx` + `TicketConversation.jsx`; `PaymentsView` -> `paymentsShared.jsx` + `PaymentParts.jsx`; `ProductsView` -> `productsShared.jsx` + `ProductParts.jsx`. Pure moves: vitest 79 / 215 pass and both builds are unchanged in size.

## T-R11 close-out: App split + gradual TypeScript (2026-11-10)
- `store-web/App.jsx` 1,084 -> ~545 lines: header, hero, plans, how/why, account banner, footer, mobile nav and the five dialog bodies (`StoreDialogs.jsx`) are components now; state and effects stay in `App` on purpose (no behaviour change, no new hooks).
- Safety net is a real browser, not only jsdom: `e2e/tests/store.purchase.spec.js` (email-code login, quote -> wallet payment -> delivery dialog, insufficient funds, bot handoff, expired handoff, Tg error redirect, mobile menu) was written and passing BEFORE the split and is identical after it (Playwright + Chromium, Core mocked with `page.route`). Run: `cd e2e && npm ci && npx playwright install --with-deps chromium && npx playwright test`. Needs Node >= 20.19 (Vite 7).
- TypeScript is started in `store-web` (strict, `allowJs`, `checkJs: false`): `coreApi.ts`, `storeProgram.ts`, `loyaltyFormat.ts` are typed; `npm run typecheck` is a CI step. Convert one leaf module per PR; do not turn on `checkJs` until the JSX components are typed.
- Source-contract guards (`check_g001_g010.py`, `check_frontend_contracts.py`, `tests/_source.read_store_shell`) read the storefront shell as App.jsx + the split files, so a guard cannot pass by looking at only half the code. First-load budget for store-web raised 272 -> 273 kB for the extra component boundaries, then 273 -> 274 kB after referral/tokens moved into packages/web-kit (measured 273.2 kB).
- Still open: admin-web has no TypeScript yet; `App` still owns session/catalog state (a `useSession` / `useCatalog` hook extraction is the next safe step, now covered by the browser specs).

## T-R11 step 2: session and catalog hooks (2026-11-10)
- `useCoreFetch` (authenticated fetch + one silent refresh) and `useStoreCatalog` (store, bundles, packages) moved out of `App`; `App.jsx` is ~470 lines.
- The first attempt put the hook calls after a line that already used `hasBot`: lint, vitest (jsdom) and `vite build` all passed, but the real browser showed a white screen (`Cannot access ... before initialization`). The Playwright specs caught it; fixed by calling the hooks before first use. Lesson: for `App` refactors the browser specs are the gate, not vitest.

## T-R11 finished: store-web fully on TypeScript (2026-11-11)
- All 48 store-web source files are `.ts`/`.tsx` (`allowJs: false`, `strict`, `tsc` 0 errors); `typecheck` is a CI step for both web apps. ESLint now parses `.ts/.tsx` too (typescript-eslint parser) with the same `--max-warnings 0` ceiling, so type migration did not drop hook/a11y linting.
- Honest limit: component props and server payloads that are not yet bound to generated `@melorin/api-client` schemas are typed `Json` / `Rec` (aliases in `src/types.ts`, same markers as admin-web). They are greppable; tighten one view per PR. This is a typed shell, not full type safety.
- Verified in a real browser, not only jsdom: Playwright 10 passed / 2 skipped (the skipped two need a seeded staging stack), vitest 79, `vite build` OK (main bundle ~272 KB, gzip ~85 KB).
- Source-contract guards (api tests, `check_g001_g010.py`, `check_frontend_contracts.py`) were repointed from `.jsx`/`.js` to `.tsx`/`.ts` for BOTH apps; the earlier admin-web migration had left 16 contract tests red because they still read the old names.

## Architecture overlap review (2026-11-13)
- `vpn` keeps the customer account lifecycle and the adapter/session layer; everything an admin does to a panel lives in `panelops`
  (`panel_admins`, `governance`, `store_usage`, `service_access`, `panel_events_admin`, `bulk`, `subscription_check`, `recreate`, `digest`).
  `vpn` never imports `panelops` (layer contract).
- Reconciliation issue actions have one owner: `panelops/reconciliation_actions.py`. The admin router validates, authorizes and serializes only.
- Payment destination has ONE model: `StorePaymentConfiguration`, for the main store too. The global `card.info` / `gateway.zarinpal` settings and the
  main-store fallback in `payments/service.store_payment_settings` are gone; alembic `0056` converts existing values once (forward-only).
  The admin edits the main store through `GET/PUT /admin/payment-destinations[/{provider}]` (area `payments`); `/admin/settings` refuses the legacy keys.
  A main store with no configuration now answers `PAYMENT_METHOD_DISABLED`, exactly like a reseller store.
- Admin menu: stores, resellers, panel access (panel admins + sub branding) and volume governance are tabs of the single `فروشگاه‌ها` hub (`#/stores?tab=...`).
- Reward stacking is written down in `domain/order_rewards.py`: coupon is already inside `order.total`; referral then loyalty settle from that charged total in a fixed order, refunds reverse loyalty then referral; the worker calls one `_settle_rewards`.
- `domain/order_state.VPN_TRANSITIONS` + `assert_vpn_transition` define the account lifecycle table; every writer goes through `set_vpn_status` (enforced by a contract test).
- Panel read cycle: `panel_health_job` takes the metrics snapshot on the SAME adapter/login as the health check (one session per panel per 2 minutes). `panel_metrics_job` no longer has its own cron (function kept for manual runs).
- Account status writes in provisioning, account_tools, bulk and reconciliation_actions go through `set_vpn_status` (guarded by `VPN_TRANSITIONS`). Renewal/returns/recreate/expiry paths that write status by other means are still to be moved.
- Notification dedup: `domain/notification_dedup.py`. The outbox hands its event id to every handler (`_event_id`); `_notify` dedupes on `event_id + recipient + channel` unless the caller already gave an explicit `dedup_key`. An outbox retry can no longer re-send to a recipient/channel that already got it.
- Guarded status writes now also cover expiry (worker/jobs), revoke (worker/runner) and panel sync (`vpn/sync.apply_remote`). Menu URLs were already stable slugs (`#/orders`, ...); the Persian label stays an internal key. Panel cards link to `#/panel-ops?panel=<id>[&tab=]`, which preselects the panel.
- Telegram: the shared bot core is `tgmain.core` (the former body of `apps/telegram-main/runner.py`). The main runner and the reseller runner are thin entry points over it; the reseller no longer loads the main `runner.py` by file path and its image copies only `tgmain`.
- Operations Center: `GET /admin/dashboard` (previously unused) now carries `attention`, a read-only roll-up of the queues other modules own (failed provisioning, discrepancies, orphans, failed panel events and bulk runs, receipt reviews, pending refunds, identity conflicts, reseller applications, open tickets). Each item names the admin section that resolves it; no remediation logic lives in the aggregate. The dashboard shows it as a card and loads it once instead of recomputing the counts client-side.
- Account status: provisioning's create/extend path now also writes through `set_vpn_status`; renewal, returns and recreate only read the status, their writes already go through guarded paths.
- Cleanup: `domain/referral.py` is folded into `domain/commission.py`, `vpn/bundles.py` became `domain/account_name.py`; dead `DataTable` branches in `AdminSections.tsx` were removed (payments and tickets are routed through `extraRoutes`).
- Panel detail: the panel-scoped tabs of the old panel-ops screen (nodes, console and subscription, live events, capacity and sales, templates, indicators and backup) are tabs of a panel detail drawer opened from the panel card (`#/panels?detail=<id>[&tab=]`). `#/panel-ops` keeps only cross-panel work: discrepancies, unknown panel users and per-store volume-notice levels (with a link to the selected panel's detail).
- Integration boundary: `modules/panel_integrations` (adapters, session, reader, capabilities, targets) is the lowest feature layer in the import-linter contract. `vpn` (customer accounts) and `panelops` (admin actions) depend on it, never the reverse.
- Shared frontend logic: `@melorin/web-kit` now holds `format.js` (digit/err helpers) and `eventCenter.js` (headless Event Center state and Core calls). Admin-web and store-web keep their own markup; the scope (main store vs reseller store) is just the `url` passed in. Backend scope enforcement is unchanged.
- Panel state has one read model: `domain/panel_snapshot.PanelSnapshot` (`snapshot_of(panel)`): health, sellable flag, live reading and freshness. Metrics endpoint and analytics read it instead of picking fields from the row. No new table: the row already stores the single per-panel read cycle's output.
- Account status writes: `tests/contracts/test_vpn_status_writes.py` fails the build on any direct `account.status = ...` outside `set_vpn_status`.
- Messaging policy: `domain/messaging_policy.py` classifies every notification kind (technical vs commercial, severity, audience, channels). Technical alerts never go to customers. It is the contract for the delivery paths; wiring each path to `allowed()` is incremental.
- Bank SMS rules (status labels, form mapping, request body) live in `@melorin/web-kit/bankSms.js` for both apps.
- Telegram DM delivery (`worker/runner._notify`) now asks `messaging_policy.dm_allowed(kind)`: kinds routed only to the Event Center (panel, backup, infra, outbox alerts) are never sent as a DM.
- VPN notices already reach customers only through `_notify` (policy-gated). Event Center keeps its own topic routing (`ADMIN_ONLY_TOPICS`, `ADMIN_COPY_TOPICS`): it never talks to customers, so `messaging_policy.allowed` adds nothing there.
- Broadcast composer logic (draft, confirm, POST, error text, delivery polling) lives in `@melorin/web-kit/broadcast.js`; both apps keep their own markup.
- Referral plan form (parsing, validation, save flow, `unitOf/toInt/percentToBp`) lives in `@melorin/web-kit/referralPlan.js`; `store-web/storeProgram.ts` re-exports the parsers.
- Loyalty club data layer (load program/rewards/summary, revision counter, write helper, default-tier fallback) lives in `@melorin/web-kit/loyaltyClub.js`; the per-card edit forms stay in each app.
- Design tokens: `@melorin/web-kit/tokens.css` holds only values identical in both skins (font stack, settle easing, pill radius, brand navy/gold) and both apps import it, so no pixel changes. The palettes still differ (admin hex variables, store RGB triplets); merging them would restyle both apps and is a product decision, not a refactor.
- Admin sync is event-driven: panel create already pushed the Operator admins at once; reseller-store creation now plans its (panel, store) rows in the same transaction. `panel_admin_sync_job` runs every 15 minutes as retry/fallback (was every minute); "sync now" stays.
- Wording: "admin" had four meanings. The UI now says «تیم مدیریت» (who signs in to Melorin) and «اپراتور پنل فروشگاه» (the PasarGuard operator of a store). Section keys changed with the labels; `SECTION_AREA` and the tests follow.
- Store Hub gained the «اعلان‌ها» tab (per-store low-traffic notice levels, moved out of panel operations; `#/panel-ops?tab=notices` is rewritten by `legacyHash`).
- `@melorin/web-kit` now also holds `PasswordInput` (inline SVG icons, no icon dependency) and the base types (`Rec`, `Json`, `CallFn`, `WithChildren`, `Toast`, `Id`); both apps' `ui.tsx`/`types.ts` re-export them. `@melorin/api-client` is already used by both apps (`getJson`, `publicGet`).
- Store Hub now has eight tabs: stores, reseller profile and bot (the former «نمایندگان» editor), panel access, volume, prices, API, notices, bot bindings. Prices is READ-ONLY (`GET /admin/stores/{id}/reseller-prices`, area catalog): only the reseller sets retail prices. API is the per-store switch (`PUT /admin/reseller-stores/{id}/api`, area resellers); both endpoints had no UI before.
- Still open (needs product input): merging the two palettes (would restyle both apps).
- Browser check: `e2e/tests/admin.storehub.spec.js` (Playwright, Core mocked) opens the Store Hub tabs, flips the API switch, follows the old notices bookmark and visits every admin menu route looking for uncaught page errors. Real-browser evidence for the mocked API only; the full stack is still unrun here.
- Worker jobs are split by domain (T10 1.3): `jobs_backup`, `jobs_panels`, `jobs_accounts`, `jobs_identity`, `jobs_payments`, `jobs_reports`. `worker/jobs.py` (516 lines before) is a 69-line facade that re-exports the 20 job functions for `arq_app` and `backup_main`; no job body changed. Collaborators (`session_factory`, `integrations`, `close_adapter` ...) are patched on the module that owns the job; tests use `tests/_jobs.patch_jobs` / `jobs_source()` for that. Verified with the full backend suite (2655 passed) and `lint-imports` (6 kept).
- Panel notices (health, nodes, settings drift, sell-guard/capacity text builders) moved from `eventcenter/rules.py` to `panelops/panel_notices.py` (T10 1.6). `eventcenter.rules` keeps only outbox-event rules (orders, payments, tickets, failures, backup). The panel module emits to the Event Center `errors` topic; delivery routing stays with the Event Center. Callers: health job, manual health check, drift job.
- Identity verification ownership (T09 1.11): `identity/auto_link` verifies CUSTOMER identity links (docs/23); `reseller/auto_verify`, `recheck`, `auto_approve` and `reseller/identity` verify RESELLER applicants during onboarding. They share domain rules in `domain/`, not code paths, so they stay separate on purpose; merging them would couple two lifecycles.
- Palette merge of admin-web and store-web is explicitly postponed by the owner (2026-11-14).
- Gate on r3 (2026-11-14): lint-imports 6/6 kept, api pytest 2655 passed / 11 skipped, admin-web typecheck+build+vitest 289 passed, store-web 79 passed. Docker stack, bots and payment gateway not run.
- UI-less admin endpoints (T09/T10 inventory, 2026-11-14) now have screens (`tools/connections` had no route, so it was a stale heuristic entry): Store Hub «اعلان‌ها» tab holds `vpn-notice-texts` (per-kind customer wording) and `vpn-digest` (owner daily digest switch; `GET vpn-notices` now also returns `daily_digest` and `has_owner`); new Store Hub «ربات‌ها» tab lists/creates `bot-store-bindings`; the bundles screen warns about `bundle-products/unassigned`; the product drawer has a per-store availability section (`products/{id}/availability`); the order drawer has an attach-account form for orders in provisioning_failed / manual_review (`orders/{id}/attach-account`); the panel detail has an «دسترسی» tab for `store-role-plan` and `service-access` (provision, rotate, keys, store role apply/revert; owner credential is sent once and cleared from the form, panel name must be typed). Vitest covers the four read/write paths; the panel-access writes need a real panel and were not exercised. Docs numbering gaps 12 and 15 are intentional (docs/00-README).

## 2026-11-14 Admin UI audit follow-up (r5)

- **Sign-in methods (Google / Telegram) moved from «هویت» to «تنظیمات» (tab `#/settings?tab=login`).** The API (`admin/integrations/*`) lives in the owner-only `system` area, while «هویت» is a `customers` screen, so support/manager roles saw a tab that answered 403. The old `#/identity?tab=login` bookmark is rewritten by `legacyHash`.
- **«هویت» now sits in the customers group** (renamed «مشتریان و فروشگاه‌ها»), no longer under «سیستم».
- **Store Hub is the only entry** for resellers, shop panel operators and volume governance: the stand-alone `extraRoutes` entries were removed; `legacyHash` keeps old bookmarks working. `SECTION_AREA` keeps their areas for the hub's tab gating.
- Server stays the authority for RBAC (`PATH_RULES` / `admin_area_guard`); the menu only hides screens.
- Not changed (needs a product decision): `bulk-operations` stays in the `infrastructure` area.
- Deferred: splitting `App.tsx` / `AdminExtra.tsx` and migrating views to `@melorin/api-client` (pure moves, own PRs).
- r5 (phase 2, first step): `AdminExtra.tsx` (750 -> 72 lines) is now only the route registry. Coupons, Settings (+ integrations, sign-in methods, change-password) and the shared table/form primitives moved verbatim to `CouponsView.tsx`, `SettingsView.tsx`, `adminExtraKit.tsx`. No behaviour change.
- r5 (phase 2, second step): `App.tsx` (987 -> ~230 lines) split verbatim into `adminNav.ts` (menu groups + hash routing), `AdminNavigation.tsx`, `AdminShell.tsx` (brand, user menu, mobile nav, clock), `AdminSession.tsx` (`useCore`, downloads/refund helpers) and `Dashboard.tsx`. The G002/G003 and frontend-contract guards now read the sum of these files.
- r5 (phase 4): browser E2E for the role matrix (`e2e/tests/admin.roles.spec.js`): menu per role, identity hub without sign-in tab, Settings sign-in tab (owner only), old bookmarks. It found that a role without access still mounted the screen (and fired its API calls) for one render before App redirected it: `AdminSectionView` now renders nothing for a forbidden section.

- r5 (verification, 2026-11-14): admin-web lint, typecheck, 299 tests (38 files), build and prettier all pass on this branch. Phase 3 (moving views to the typed api-client) is deliberately left for later, per the audit: gradual, endpoint by endpoint, not in this PR. Patch files: `patches/fix-arch-admin-ui-r5-identity-nav.*`.

- r5 (phase 3, first step): `typedClient(base)` in `admin-web/src/api.ts` is the typed `@melorin/api-client` on the same transport rules as `authFetch` (in-memory bearer token, one shared refresh on 401). Identity reviews (list/dismiss/reopen) and Payments (list, destinations get/put) now use it; the remaining dynamic-path calls stay on `authFetch` until each endpoint is migrated. Note: the OpenAPI schema renders free-form objects as `Record<string, never>`, so destination bodies are cast once at the call site.
- r5 (phase 4, real stack, 2026-11-14): Docker Compose (postgres, redis, api, worker, store-web, admin-web) built and run from an empty DB through migration 0056; `scripts/e2e_smoke.py` (mock panel) passed all checks (wallet top-up approval, purchase, provisioning, outbox, 401/403, throttling). Finding fixed: refunding a payment whose provider has no automatic refund (manual card) raised an unhandled `NotImplementedError` (HTTP 500); it is now a 409 `REFUND_NOT_SUPPORTED` with the money untouched, with a regression test. Selected API tests (payments, wallet ledger, order money, contracts): 548 passed, 1 skipped; `lint-imports` 8/8. Still NOT run: a real PasarGuard panel, Telegram bots, Caddy/Prometheus/Alertmanager, a live Zarinpal sandbox, the Playwright suite against Compose, and the full API suite.

- r5 (phase 4, real PasarGuard, 2026-11-14): a live PasarGuard panel was registered in the Compose stack with an API key (read-only checks only, no accounts created or changed on the panel). Panel registration, adapter health check and reconciliation all worked: health reported `degraded` because 4 of 8 panel nodes could not be reached from the panel itself (panel-side), reconciliation completed with 0 errors and listed the 2 panel users Melorin does not know as orphans. Not covered: provisioning/renewal/deletion of a real account, node traffic, and `scripts/pasarguard_contract.py diff` (the panel hides its public OpenAPI; export it inside the container as the script documents).

- r5 (phase 4, real PasarGuard lifecycle, 2026-11-14): on a dedicated test panel the full customer flow ran twice end to end: top-up approval -> wallet purchase -> worker provisioning -> the panel user exists with the right group, 1 GB quota and expiry -> admin suspend (panel `disabled`) -> resume (panel `active`) -> subscription rotate -> usage read -> customer return (wallet refunded, panel user deleted). No leftover panel users after either run. The first renewal attempt failed only because the test script sent the wrong field name (`account_id` instead of `vpn_account_id`); with the right field, a renewal order on the real panel completed and moved the panel expiry to now + the package duration (`replace` mode). Returning an account after a renewal is refused by design (`RETURN_RENEWED`). The panel test users were removed afterwards.

- r5 (phase 4, browser): the Playwright suite (`e2e/`, real Chromium, mocked Core API) passed on a clean server: 26 passed, 2 skipped, including the role matrix, every admin menu route and Store Hub deep links. It runs against the Vite preview builds, not against the Compose stack.
- r5 (menu, 2026-11-14): bulk operations stays in the `infrastructure` permission area (it changes accounts on the external panel); the menu label is now «عملیات گروهی روی پنل» so the label matches who may use it. The URL slug `bulk-operations` is unchanged.
- r6 (phase 3, second step, 2026-11-14): Orders actions (retry / manual-review / refund) moved to `typedClient`, one literal path per action so the schema checks each body. The client consumes the response body, so failures read the message from its parsed `error`. Remaining on `authFetch`: Panel Operations and the other views, migrated endpoint by endpoint.
- r6 (phase 3, third step, 2026-11-14): Panel Operations write calls (reconciliation issue action, panel reconcile, orphan ignore) moved to `typedClient`; no new loose Json/Rec types (typing ratchet stays green). Panel Operations reads and the capacity/events tabs stay on `authFetch` for now.
- r6 (phase 3, fourth step, 2026-11-14): Panel Operations reads (panels, reconciliation summary/issues, orphans) go through `getJson` from `@melorin/api-client`; PanelOpsView no longer uses `authFetch`. The capacity and events tabs of the panel drawer still take an `authFetch`-based `call` prop.
