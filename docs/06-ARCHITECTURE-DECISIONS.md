# تصمیم‌های معماری / Architecture Decisions

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** تصمیم‌های تأییدشده، دلایل و تصمیم‌های superseded.



## English section

**Purpose:** Confirmed decisions, rationale and superseded decisions.



## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `06-ARCHITECTURE-DECISIONS.md`

#### Melorin ADR / open decisions

##### Decided in V1
- Modular monolith; only Core owns PostgreSQL and business rules.
- PostgreSQL ledger is append-only source of truth; balance is a locked projection.
- Internal transactional outbox, polling worker in V1; broker remains replaceable.
- Sanaei and PasarGuard adapters implement one standard interface.
- Manual card receipt flow ships; online gateway adapter is optional and disabled until configured.
- Admin can manually review/retry/attach/refund; provisioning failure never auto-refunds.
- Iranian Rial is default currency, amounts are integers in smallest canonical unit.

##### Must be approved before production
- Exact email authentication provider/SMTP and Google OAuth production settings.
- Final debt-limit boundary, reseller wallet funding/adjustment policy, commission debt policy.
- Referral attribution scope (platform vs store).
- JWT/session policy, Celery/ARQ choice, Caddy/Nginx, Sentry and metrics stack.
- S3-compatible storage, RPO/RTO, backup target and restore-test schedule.
- Telegram Event Center group/topic permissions and bot token ownership.
- Admin account bootstrap and mandatory/optional 2FA policy.

Open decisions are runtime-configurable where safe, but are not silently treated as requirements.

##### v1.1 decisions applied (2026-10-09)

_Merged from the former 12-Change-Log-v1.1.md._

تاریخ: 2026-10-09

این نسخه بر اساس پاسخ‌های مالک محصول به سؤالات باز به‌روزرسانی شده است.

###### تصمیم‌های اعمال‌شده
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

###### موارد باز باقی‌مانده
در سند `21-ROADMAP-TECHNICAL-DEBT.md` ثبت شده‌اند؛ از جمله درگاه پرداخت، Email Auth، روش تمدید، Reverse Proxy، Storage، Session/JWT، Monitoring stack، بازیافت کمیسیون خرج‌شده، تنظیم گروه‌های تلگرام و سیاست‌های تکمیلی ارز و شارژ دستی.

##### T39 / T36 - coverage floors and migration formatting (2026-11-10)
- Money-handling code has its own line-coverage floors enforced by `scripts/check_coverage_floors.py` in CI (domain 92%, wallet 88%, payments 85%, orders 88%, `core/uow.py` 90%), on top of the global 75% net. Measured on 2026-11-10: 97.4 / 93.2 / 91.0 / 93.1 / 100. Raise floors as coverage grows; do not lower one without recording why here.
- `alembic/` is now covered by `ruff format --check` (CI and `make lint`). The 37 migration files were reformatted only; the full non-integration suite (2390 tests, incl. the migration baseline contract) passes unchanged.

##### T16 / T65 - panel families kept, as plug-in adapters (2026-11-10)
- Decision: `sanaei`, `pasarguard` and `upstream_bot` all stay. None is removed; each is a provider adapter declared in `modules/panel_integrations/adapters/providers.py` (`ProviderSpec`: label, transport, features, target kinds, adapter path, contract path).
- Adapter classes and each family's `contract.py` (settings/target validation, capacity label, listing warnings) are imported lazily; `upstream_bot` therefore needs Telethon only when a call is made.
- Core code asks `providers.supports(kind, feature)` / `target_kinds(kind)` instead of comparing `panel.kind` with a string. A new family is one `register_provider(...)` call.
- Guarded by `tests/test_provider_adapters.py` (no concrete family is imported outside the adapter layer, except the PasarGuard wire parsers listed in the test).

##### T-R10 - `reportsLogic.js` stays in admin-web; branch hygiene (2026-11-10)
- Review of `apps/admin-web/src/reportsLogic.js` (194 lines): it only formats numbers (`fmt*`), maps labels, draws donut/heat geometry and derives percentage shares and insight sentences from figures that Core already returned. It never computes balances, prices, fees or ledger values, so it is presentation logic and stays in the UI.
- Rule going forward: if a report needs a *new* monetary figure (a total, margin, balance), Core's reports module must return it as a field; the browser may only format and compare it. Same rule as the quote's `balance_after` / `shortfall` (T-R10).
- Branch hygiene (T-W16): the 19 remote branches fully merged into `main` were deleted on 2026-11-10; every commit remains reachable from `main`. Unmerged branches were kept for the owner to decide.

##### T-R05 / T-R07 / T-R12 / T-R13 / T-R14 / T-R15 - remediation close-out and deferred work (2026-11-10)
- Done: pasarguard test files are named by feature (`admin_api`, `service_db`, `events`, `account_tools`, `capacity`, `bulk_ops`, `ops_governance`, `ops_maturity`, ...) instead of `phaseN`; `test_q02_bot_inquiry` became `test_bot_inquiry`; panel documents live in `docs/panels/`.
- Done: the PostgreSQL lane (`postgres-lane` in `ci.yml`) is a normal required job (no `continue-on-error`); broad `except Exception` handlers are ratcheted by `test_broad_except_exception_count_only_ratchets_down` (ceiling 104, lower it when you narrow one).
- Deferred on purpose, each needs a real Docker host or product input that this remediation did not have:
  - T-R14 backup out of the Worker: moving `backup_job`/`panel_backup_job` into a dedicated ops container changes the compose topology and the restore drill; do it together with a first compose run on a Docker host.
  - T-R13 OpenTelemetry exporter and a CI performance budget: tracing now exists without new dependencies (see "Trace context" below); an exporter needs a collector decision and hash-locked packages. The `load_probe.py` budget needs the full stack.
  - T-R11 remaining: `store-web/App.jsx` still holds the 1,000-line `App` component and the three admin views were split by block, not by feature; keep going one view per PR with the vitest suites as the safety net. Gradual TypeScript is not started.
  - T-W08 ESLint ceilings stay at 13 / 25: each remaining warning is a `react-hooks/exhaustive-deps` case where a blind fix can loop or refetch, so they need a browser check, not a bulk edit.
  - Merging the pasarguard test files into ~6 files: renames are done; physical merging is cosmetic and was left out to keep git history of each suite readable.

##### Trace context (T-G06, 2026-11-10)
- `CorrelationMiddleware` honours an inbound W3C `traceparent` (or creates a trace id), echoes `traceparent` on the response, and every JSON log line carries `trace_id`. `core/http.outbound_client` forwards the same trace id to peers. No SDK, collector or new dependency; `traceparent` is in the CORS allow-list. Tests: `tests/unit/test_tracing.py`.

##### T-R11 first split (2026-11-10)
- `store-web/App.jsx`: static copy, constants, `Logo` and `HeroVisual` moved to `landing.jsx`.
- `admin-web`: `TicketsView` -> `ticketsShared.jsx` + `TicketConversation.jsx`; `PaymentsView` -> `paymentsShared.jsx` + `PaymentParts.jsx`; `ProductsView` -> `productsShared.jsx` + `ProductParts.jsx`. Pure moves: vitest 79 / 215 pass and both builds are unchanged in size.

##### T-R11 close-out: App split + gradual TypeScript (2026-11-10)
- `store-web/App.jsx` 1,084 -> ~545 lines: header, hero, plans, how/why, account banner, footer, mobile nav and the five dialog bodies (`StoreDialogs.jsx`) are components now; state and effects stay in `App` on purpose (no behaviour change, no new hooks).
- Safety net is a real browser, not only jsdom: `e2e/tests/store.purchase.spec.js` (email-code login, quote -> wallet payment -> delivery dialog, insufficient funds, bot handoff, expired handoff, Tg error redirect, mobile menu) was written and passing BEFORE the split and is identical after it (Playwright + Chromium, Core mocked with `page.route`). Run: `cd e2e && npm ci && npx playwright install --with-deps chromium && npx playwright test`. Needs Node >= 20.19 (Vite 7).
- TypeScript is started in `store-web` (strict, `allowJs`, `checkJs: false`): `coreApi.ts`, `storeProgram.ts`, `loyaltyFormat.ts` are typed; `npm run typecheck` is a CI step. Convert one leaf module per PR; do not turn on `checkJs` until the JSX components are typed.
- Source-contract guards (`check_g001_g010.py`, `check_frontend_contracts.py`, `tests/_source.read_store_shell`) read the storefront shell as App.jsx + the split files, so a guard cannot pass by looking at only half the code. First-load budget for store-web raised 272 -> 273 kB for the extra component boundaries, then 273 -> 274 kB after referral/tokens moved into packages/web-kit (measured 273.2 kB).
- Still open: admin-web has no TypeScript yet; `App` still owns session/catalog state (a `useSession` / `useCatalog` hook extraction is the next safe step, now covered by the browser specs).

##### T-R11 step 2: session and catalog hooks (2026-11-10)
- `useCoreFetch` (authenticated fetch + one silent refresh) and `useStoreCatalog` (store, bundles, packages) moved out of `App`; `App.jsx` is ~470 lines.
- The first attempt put the hook calls after a line that already used `hasBot`: lint, vitest (jsdom) and `vite build` all passed, but the real browser showed a white screen (`Cannot access ... before initialization`). The Playwright specs caught it; fixed by calling the hooks before first use. Lesson: for `App` refactors the browser specs are the gate, not vitest.

##### T-R11 finished: store-web fully on TypeScript (2026-11-11)
- All 48 store-web source files are `.ts`/`.tsx` (`allowJs: false`, `strict`, `tsc` 0 errors); `typecheck` is a CI step for both web apps. ESLint now parses `.ts/.tsx` too (typescript-eslint parser) with the same `--max-warnings 0` ceiling, so type migration did not drop hook/a11y linting.
- Honest limit: component props and server payloads that are not yet bound to generated `@melorin/api-client` schemas are typed `Json` / `Rec` (aliases in `src/types.ts`, same markers as admin-web). They are greppable; tighten one view per PR. This is a typed shell, not full type safety.
- Verified in a real browser, not only jsdom: Playwright 10 passed / 2 skipped (the skipped two need a seeded staging stack), vitest 79, `vite build` OK (main bundle ~272 KB, gzip ~85 KB).
- Source-contract guards (api tests, `check_g001_g010.py`, `check_frontend_contracts.py`) were repointed from `.jsx`/`.js` to `.tsx`/`.ts` for BOTH apps; the earlier admin-web migration had left 16 contract tests red because they still read the old names.

##### Architecture overlap review (2026-11-13)
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

##### 2026-11-14 Admin UI audit follow-up (r5)

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

- r5 (phase 3, first step): `typedClient(base)` in `admin-web/src/api/api.ts` is the typed `@melorin/api-client` on the same transport rules as `authFetch` (in-memory bearer token, one shared refresh on 401). Identity reviews (list/dismiss/reopen) and Payments (list, destinations get/put) now use it; the remaining dynamic-path calls stay on `authFetch` until each endpoint is migrated. Note: the OpenAPI schema renders free-form objects as `Record<string, never>`, so destination bodies are cast once at the call site.
- r5 (phase 4, real stack, 2026-11-14): Docker Compose (postgres, redis, api, worker, store-web, admin-web) built and run from an empty DB through migration 0056; `scripts/e2e_smoke.py` (mock panel) passed all checks (wallet top-up approval, purchase, provisioning, outbox, 401/403, throttling). Finding fixed: refunding a payment whose provider has no automatic refund (manual card) raised an unhandled `NotImplementedError` (HTTP 500); it is now a 409 `REFUND_NOT_SUPPORTED` with the money untouched, with a regression test. Selected API tests (payments, wallet ledger, order money, contracts): 548 passed, 1 skipped; `lint-imports` 8/8. Still NOT run: a real PasarGuard panel, Telegram bots, Caddy/Prometheus/Alertmanager, a live Zarinpal sandbox, the Playwright suite against Compose, and the full API suite.

- r5 (phase 4, real PasarGuard, 2026-11-14): a live PasarGuard panel was registered in the Compose stack with an API key (read-only checks only, no accounts created or changed on the panel). Panel registration, adapter health check and reconciliation all worked: health reported `degraded` because 4 of 8 panel nodes could not be reached from the panel itself (panel-side), reconciliation completed with 0 errors and listed the 2 panel users Melorin does not know as orphans. Not covered: provisioning/renewal/deletion of a real account, node traffic, and `scripts/pasarguard_contract.py diff` (the panel hides its public OpenAPI; export it inside the container as the script documents).

- r5 (phase 4, real PasarGuard lifecycle, 2026-11-14): on a dedicated test panel the full customer flow ran twice end to end: top-up approval -> wallet purchase -> worker provisioning -> the panel user exists with the right group, 1 GB quota and expiry -> admin suspend (panel `disabled`) -> resume (panel `active`) -> subscription rotate -> usage read -> customer return (wallet refunded, panel user deleted). No leftover panel users after either run. The first renewal attempt failed only because the test script sent the wrong field name (`account_id` instead of `vpn_account_id`); with the right field, a renewal order on the real panel completed and moved the panel expiry to now + the package duration (`replace` mode). Returning an account after a renewal is refused by design (`RETURN_RENEWED`). The panel test users were removed afterwards.

- r5 (phase 4, browser): the Playwright suite (`e2e/`, real Chromium, mocked Core API) passed on a clean server: 26 passed, 2 skipped, including the role matrix, every admin menu route and Store Hub deep links. It runs against the Vite preview builds, not against the Compose stack.
- r5 (menu, 2026-11-14): bulk operations stays in the `infrastructure` permission area (it changes accounts on the external panel); the menu label is now «عملیات گروهی روی پنل» so the label matches who may use it. The URL slug `bulk-operations` is unchanged.
- r6 (phase 3, second step, 2026-11-14): Orders actions (retry / manual-review / refund) moved to `typedClient`, one literal path per action so the schema checks each body. The client consumes the response body, so failures read the message from its parsed `error`. Remaining on `authFetch`: Panel Operations and the other views, migrated endpoint by endpoint.
- r6 (phase 3, third step, 2026-11-14): Panel Operations write calls (reconciliation issue action, panel reconcile, orphan ignore) moved to `typedClient`; no new loose Json/Rec types (typing ratchet stays green). Panel Operations reads and the capacity/events tabs stay on `authFetch` for now.
- r6 (phase 3, fourth step, 2026-11-14): Panel Operations reads (panels, reconciliation summary/issues, orphans) go through `getJson` from `@melorin/api-client`; PanelOpsView no longer uses `authFetch`. The capacity and events tabs of the panel drawer still take an `authFetch`-based `call` prop.
- r6 (verification, 2026-11-14, base 0ffcef6): full API suite 2720 passed, 11 skipped (9 min, Python 3.12, locked requirements); lint-imports 8/8 kept; admin-web typecheck, lint, build, prettier and the frontend/G001-G010 guards pass. Still not run in this round: migrations from the previous version, full Compose with the new commits, Playwright against Compose.
- r6 (verification, PostgreSQL, 2026-11-14): on a throwaway postgres:16-alpine, `scripts/migration_smoke.sh` ran from an empty database to the current head (see docs/STATUS.md) and passed; the PostgreSQL lane (`tests/postgres`, via TEST_PG_URL) passed 8/8. Not run: upgrade from a previous-version database, full Compose with the r6 commits, Playwright against Compose.

- r7 (phase 3, fifth step, 2026-11-14): the panel drawer's capacity and live-events tabs no longer take the `authFetch`-based `call` prop. They receive `api` and read through `getJson` and write through `typedClient` (one literal path per action, so the schema checks each body). Same transport rules as before (in-memory bearer token, one shared refresh on 401). Capacity/events tests now mock `fetch`. Still on `authFetch` `call`: nodes, console, templates, observe (phase 5) and access tabs, and the remaining non-panel views; they move endpoint by endpoint.

- r8 (phase 3, sixth step, 2026-11-14): the panel drawer's nodes and observe (metrics, settings drift, lifecycle policy, panel backups) tabs take `api` and use `getJson` / `typedClient` (drift check POST and lifecycle-policy PUT are typed). Still on the `authFetch` `call` prop: console and subscription, templates, access tabs (dynamic paths and error-body handling; migrate with their own tests), plus the non-panel views.

- r9 (phase 3, seventh step, 2026-11-14): the panel drawer's templates tab takes `api`; list reads use `getJson`, and create / link / sync / enable / disable / unlink are typed calls with one literal path each. Still on the `authFetch` `call` prop: console and subscription (family-dependent toggle paths and the LAST_NODE retry) and access tabs, plus the non-panel views.

- r10 (phase 3, eighth step, 2026-11-14): the last panel drawer tabs, console/subscription and access, take `api` and use the typed client (literal paths; the node action and family toggle use the schema's `{action}` / `{family}` path params; the LAST_NODE confirm-and-retry is kept). `PanelDetailTabs` no longer builds an `authFetch` `call`: every tab of the panel drawer is on `getJson` / `typedClient`. Access-tab writes (provision, rotate, store role apply/revert, list keys) need a real panel and were not exercised, only type-checked and covered by the existing tests. Remaining on `authFetch`: the non-panel views (see `grep authFetch apps/admin-web/src`).

- r10 verification (2026-11-14, Python 3.12, locked requirements): full API suite 2720 passed, 11 skipped (9 min); `lint-imports` 8/8 kept.
- r11 (phase 3, ninth step, 2026-11-14): Payments review (approve/reject) and refund are typed `client.post` calls with one literal path each. The receipt image stays on `authFetch` (binary body). The slow `panels-upstream-bot` creation test got a 20 s timeout: it timed out at the 5 s default when the box was loaded, unrelated to the code. Remaining on `authFetch`: receipt review/OCR/duplicate-policy/bank-SMS panels, Settings, products, bundles, tickets, reports and other views.
- r12 (phase 1 + 3, 2026-11-14): (a) Settings gets its own owner-only tab «امنیت دسترسی ادمین» (`#/settings?tab=security`) for the admin IP allowlist: it is a security policy, not an integration, so the first tab is now only SMTP/backup. Same server area (`system`), same endpoint; only the UI placement moved. (b) The last nav group is renamed «سیستم و امنیت» (labels only, section keys and permission areas unchanged). (c) Identity hub: trusted-device summary and the revoke / revoke-account actions use the typed client (literal path per action); list reads stay on `useRows`. Remaining on `authFetch`: see `grep authFetch apps/admin-web/src`.
- r12 verification (2026-11-15, Python 3.12, Node 22, Docker 29): full API suite 2720 passed, 11 skipped; admin tests 301 passed; `lint-imports` 8/8; fresh-DB `migration_smoke.sh` to head passed on PostgreSQL 16; `docker compose up --build` brought every service healthy (run `alembic upgrade head` BEFORE the first start, as `melorin.sh` does; the api logs `relation stores does not exist` otherwise); live `scripts/e2e_smoke.py` against the stack: ALL PASSED; Playwright (store + admin, mocked Core): 26 passed, 2 skipped (need a seeded staging stack). Fix: `ChangeAdminPassword` moved out of `SettingsView.tsx` into its own file, so Settings is a real lazy chunk (Vite warned it was imported both statically and dynamically). Bot, payment-gateway and real-panel flows remain unexercised.

##### 2026-11-15 Pre-release architecture audit follow-up (r13, branch `refactor/audit-pre-release-r12`)

Source: `Melorin_Architecture_Admin_Audit.md` (the project has never been released, so menu and compose structure may change freely; money, security and state machines still need tests).

- **Menu regrouped by the admin's job** (`adminNav.ts`): نمای کلی / فروش و عملیات / مشتریان / فروشگاه‌ها و نمایندگان / کاتالوگ و بازاریابی / زیرساخت و عملیات پنل / اعلان‌ها، ارتباطات و پشتیبانی (پیام همگانی، مرکز رویداد، تیکت‌ها؛ فقط گروه‌بندی UI و بدون ادغام ماژول‌های backend) / سیستم و امنیت. Section keys (Persian labels) and slugs are unchanged except the removed one below, so permissions and deep links keep working.
- **«عملیات گروهی روی پنل» moved to the infrastructure group** (it already used the `infrastructure` permission). Whether support may also run bulk operations stays a product decision: if yes, add a narrow dedicated permission, never the whole `infrastructure` area.
- **«کارهای دستی» has no menu entry any more**: it is the tab «اقدامات تکمیلی» of «درخواست‌های نمایندگی» (`ResellerOnboardingView`, `#/reseller-applications?tab=tasks`). The tab is shown only to roles with the `customers` area (the manual-tasks API rule); the menu badge sums pending applications and open tasks. `legacyHash` rewrites `#/manual-tasks`. The API is untouched.
- **«دکمه‌های تلگرام» moved to «سیستم و امنیت»**: its permission is `system` (owner only), so it now sits with the owner-only settings instead of the communications group where a manager would see a wall of 403s.
- **Compose: one-shot `migrate` service** (`alembic upgrade head`). `api`, `worker` and `backup` wait for `service_completed_successfully`, so a bare `docker compose up -d` on a fresh host cannot start against an empty schema. `check_ops_p0.py` skips `restart: "no"` one-shot jobs in the memory sum (it has exited before the others start) and allows that policy for `migrate` only. `melorin.sh` / `deploy.sh` keep their explicit migration step (idempotent, and deploy needs it for rollback).
- **web-kit has a lockfile**; `check_web_lockfiles.py` covers it and CI runs `npm ci` + `npm audit --omit=dev` there.
- **Typed-client ratchet** (`tests/authfetch-ratchet.test.js`): `authFetch(` call sites may only shrink (budget 2 after three batches: every view now reaches the network through `typedClient` (literal paths) or the single `useCall` hook in `api.ts` (generic paths fed to shared helpers such as `useRows` and the web-kit hooks); the two remaining raw `authFetch` calls are binary downloads (orders.csv, report exports). Migration order from the audit: Settings, Products, Bundles, Tickets, Reports, Store tabs, Resellers.
- **Vulture findings were false positives, now explicit**: `initiator` is the mandatory SQLAlchemy listener argument (renamed `_initiator`); `CursorResult` is named only inside a string `cast`, so it moved under `TYPE_CHECKING`.
- Kept on purpose (audit §4, §7.6): Payments / Wallet, Orders / Provisioning, Identity / Authentication, PanelOps / Panel Integrations, Event Center / Notifications stay separate.
- Still open (own PRs, not done here): move `/admin/reports/summary` and `/timeseries` into the analytics contract and switch `AdminSession.tsx` / `Trend.tsx` first; split `PanelAdminsView`, `kit.tsx`, `UpstreamBotFields`, `TicketConversation`, `ReportsView` as pure moves; widen mypy module by module (orders, identity, reseller, payments); drop `modules/admin/router.py` re-exports once no import uses them; split `panelops` files by capability.

##### r13b - mypy scope widened to orders, identity, reseller (audit 8.5)
- **Decision:** orders, identity and reseller are now inside the mypy gate. 9 files (14 at first; 4 cleaned in r13d via crypto overloads, orders payment in r13e with None-guard tests) that still carry Optional-narrowing errors (61 in total, mostly session.get() results used without a None check, in payment/provisioning/identity-merge paths) sit in an ignore_errors override list.
- **Why a ratchet and not a mass fix:** these are money and provisioning paths; a blind assert or default value could change behaviour. Each file is cleaned together with a test that proves the None case, then removed from the list.
- **Rule:** the list may only shrink. tests/contracts/test_mypy_ratchet.py fails if it grows.

##### r14 - audit follow-up (branch `refactor/audit-pre-release-r14`)
- `modules/admin/router.py` is now only the composition root: the `__getattr__` re-export shim is removed and every test imports from the owning route module.
- Pure moves (no logic change): `PanelAdminsView` -> `panelAdminsShared`, `PanelAdminDrawer`, `PanelRequestDrawer`; `TicketConversation` -> `TicketBubble`, `TicketComposer`; `UpstreamBotFields` -> `UpstreamFlowParts`; `kit.tsx` -> `kitFormat`, `kitDisplay`, `kitFilters`, `kitOverlays` (re-exported from `kit.tsx`).
- Reports vs Overview: the `/admin/reports/summary` calculation moved to `modules/reports/summary.py`; the Overview route only composes it. Paths and payloads are unchanged, because `AdminSession.tsx` and `Trend.tsx` still consume `/summary` and `/timeseries`; retiring them means moving both screens onto the analytics payload first.
- mypy now covers `modules/payments` with no ratchet entries (66 errors fixed). Behaviour changes, all failure paths: `mark_succeeded` / `mark_failed` on an unknown payment and `refund_payment` / callback on a vanished store return a 404 AppError instead of an AttributeError; the gateway callback keeps only string form fields; the receipt upload stores `""` instead of `None` as content type. Tests: `tests/unit/test_payments_service_guards.py`.
- Still open: move `AdminSession.tsx` / `Trend.tsx` to the analytics payload and then retire `/summary` and `/timeseries`; clear the last ratchet file (`orders/provisioning.py`, 14 Optional-narrowing errors on panel/server placement: needs a design decision on what a missing panel means mid-provisioning); a limited support permission for bulk panel operations (product decision).
- r14c: eight of nine ratchet files are clean and out of the list (`MAX_RATCHET` 9 -> 1). Failure-path behaviour only: a dangling identity/link-code user is a 404 `USER_NOT_FOUND` (`identity/service._owner_of`, Google login), `try_auto_merge` returns nothing when a merge result carries no keeper/shell, reseller auto-approval passes `""` for a missing domain/bot key, the DNS TXT check treats a missing `Answer` as no records. Test: `tests/unit/test_identity_dangling_user.py`.

##### r15 - audit follow-up (branch `refactor/audit-r15-impl`)
- `orders/provisioning.py` is typed and the mypy ratchet is empty (`MAX_RATCHET = 0`, no `[[tool.mypy.overrides]]`). Design decision for the open question "what does a missing panel mean mid-provisioning": an order whose account points at a deleted panel or server stops in `provisioning_failed` with `needs_review = true` (a data defect no retry can fix), exactly like the existing renewal-without-template case; it never crashes with `AttributeError` and never guesses a replacement panel.
- Legacy hash aliases are gone (`legacyHash`, `LEGACY` in `infra.tsx`): Melorin has never been released, so no bookmark needs a rewrite. Menu slugs are the only addresses. `infraHref` stays for building deep links.
- Reports own `/admin/reports/*`: `summary`, `timeseries`, `analytics`, `analytics.csv` and `orders.csv` moved from `admin/overview.py` to `modules/reports/admin_router.py` (paths and payloads unchanged, attached to the admin composition root). Overview keeps only the dashboard queue, health and backup status. `/summary` and `/timeseries` are NOT retired: they are the all-time, every-currency dashboard contract, while `/analytics` is one currency over one period, so the analytics payload cannot replace them without losing the multi-currency headline cards. They stay documented here as the dashboard contract of Reports.
- Store hub: the eight tabs are drawn as three captioned groups (profile, operational settings, integrations and access) under the heading «مدیریت فروشگاه‌ها و نمایندگان». Tab ids, permissions and `?tab=` deep links are unchanged.
- Admin Team permission matrix, final: bulk panel operations stay `infrastructure` only; support gets no bulk operation. If support ever needs one, add a narrow dedicated permission, never the whole `infrastructure` area. Telegram buttons stay `system` (owner) and sit in «سیستم و امنیت».
- Remaining `authFetch(` call sites (2) are binary CSV downloads (`reports/orders.csv`, report export), which need the raw `Response` and so cannot go through the JSON typed client; they keep the same transport rules.
- r15 verification (2026-11-15, Ubuntu, Python 3.12, Node 22, PostgreSQL 16 from apt, no Docker): API suite (`-m 'not integration and not concurrency'`) 2726 passed, 1 skipped; `tests/postgres` lane 8 passed against a real PostgreSQL; `alembic upgrade head` from an empty database reached the current head (see docs/STATUS.md) and `alembic check` reported no model drift; `mypy` clean with an empty ratchet; admin-web `tsc`, `eslint`, vitest 303 passed. Downgrade is intentionally blocked (restore from backup). Still NOT run here: Docker Compose, real panels, Telegram bots, backup/restore drill, Playwright; run `make deploy-test` on a Docker host before the first release.
- r15 real-stack evidence (2026-11-15, Docker 29 + Compose 2.40 on the test server): `docker compose build` of all 8 images; a bare `up` ran the one-shot `migrate` to exit 0 on an empty database before api/worker/backup started (audit 8.2 confirmed live); `scripts/e2e_smoke.py` against the real stack: ALL PASSED (wallet top-up, purchase, provisioning via worker, outbox, 401/403, channel mismatch, throttling); Playwright (store + admin, built apps with mocked Core): 24 passed, 2 skipped; real encrypted backup (`backup_secure.sh`) and restore drill (`backup_restore_drill.sh` + `backup_restore_verify.sh`): passed, 76 tables restored.
- **Restore-drill finding, fixed:** `backup_secure.sh` called the `pg_dump` wrapper, which picks client 17 in the image (clients 16 and 17 are installed); that archive could NOT be restored into the PostgreSQL 16 server (`unrecognized configuration parameter "transaction_timeout"`). The script now asks the server for `server_version_num` and runs the matching `/usr/lib/postgresql/<major>/bin/pg_dump`. Guarded by `tests/contracts/test_backup_dump_client_matches_server.py`. Backups already made before this fix by the 17 client must be restored with a 17 server or client.
- Playwright specs for the removed legacy bookmarks were deleted; the store-hub spec now expects three captioned groups with eight tabs.
- Still NOT run: a real PasarGuard panel, Telegram bots against Telegram, Caddy/Prometheus/Alertmanager profile, Zarinpal sandbox.

##### r16 - audit follow-up (branch `refactor/audit-r16-impl`)
- **mypy now gates the whole backend** (`files = ["melorin"]`, no ratchet entries): reports, tickets, notifications, loyalty, webhooks, vpn_accounts, admin, panelops, channels and the panel_integrations adapters joined the earlier packages (audit 8.5). Type-only fixes except the failure paths below.
- Adapter mixins (`pasarguard/*`, `sanaei/*`) declare what their host class provides inside `if TYPE_CHECKING:` blocks (no runtime change). Optional adapter capabilities (`ensure_role`, `list_hosts`, ...) are reached through `optional_ops(adapter)` in `adapters/base.py`, always after a `supports()` gate.
- Failure-path behaviour changes (a missing row used to raise `AttributeError`, now a clean answer): `reconcile_account` returns `missing` for a deleted panel; admin ticket message edit, panel admin password reset, server patch with a vanished panel, reconciliation issue action without an account and reseller approval without a target store answer 404 `NotFound`; the panel webhook for a vanished panel answers 401.
- `panelops/bulk.py` is split: lifecycle and reporting stay in `bulk.py`, the worker side (`claim_next`, `execute`, `run_next`) moved unchanged to `panelops/bulk_runner.py`. The commit ratchet follows (6 + 6 = the old 12).
- Infrastructure menu (audit 5.6): three entries, «پنل‌ها و سرورها», «پایش و سلامت» (was «سلامت زیرساخت») and «عملیات مدیریتی» (one hub, tabs «عملیات پنل» and «عملیات گروهی»; `#/panel-ops?tab=bulk`). The stand-alone bulk entry and its slug `bulk-operations` are gone; the dashboard queue «failed_bulk_operations» now links to `panel-ops`. Permission stays `infrastructure` for all three.

##### r17 - audit verification (branch refactor/audit-r17-impl)
- Re-checked every audit item against the r16 code: sections 5, 6, 7, 8.1-8.3, 8.5 and 9 have nothing left open. Menu regroup, Store hub, migrate compose service, web-kit lockfile, whole-backend mypy, panelops split by capability, no router re-exports, no legacy hash aliases, Reports owning /admin/reports/* are in place and test-guarded.
- Kept on purpose (audit 7.3): /admin/reports/summary and /timeseries are the all-time multi-currency dashboard contract, not duplicates of /analytics.
- Product decisions unchanged from r15: bulk panel operations stay infrastructure-only, Telegram buttons stay system (owner).
- r17 verification (2026-11-15, Ubuntu 24.04, Python 3.12, Node 22): lint-imports 8 contracts kept, ruff check and format clean, mypy clean on 349 files, admin-web eslint clean and vitest 303 passed, API suite (not integration, not concurrency) 2728 passed, 1 skipped after fixing 3 bulk tests that now patch bulk_runner.CHUNK.
- r17 stabilization evidence: tests/postgres lane 8 passed on real PostgreSQL 16; alembic upgrade head from an empty DB reached the current head (see docs/STATUS.md) and alembic check found no drift. Not run here: upgrade from an older DB, real panels, Telegram bots, Playwright, backup restore drill (needs a Docker host).

##### r18 - audit implementation (branch refactor/audit-r18-impl)
- Tickets moved to the menu group «اعلان‌ها، ارتباطات و پشتیبانی» (with broadcasts and the event center). UI grouping only: no backend module is merged. Still 8 groups; role matrix pinned by `nav-role-matrix.test.js`.
- Large backend files split behind unchanged facades (`payments.bank_sms` package, `loyalty.service`, `referral.service`, `reports.analytics`). Public names, worker patch points and API contracts are unchanged. `upstream_bot/adapter.py` is intentionally left whole (ordered bot protocol).
- Dead code removed (unreferenced functions, schemas and admin-web exports). Backend modules are kept.
- admin-web moved to `app/`, `api/`, `features/*` (pure moves). `docs/21-ROADMAP-TECHNICAL-DEBT.md` is the live audit status and debt register; `docs/21-ROADMAP-TECHNICAL-DEBT.md` is historical.

##### r19 - audit leftovers (branch refactor/audit-r19-impl)
- `upstream_bot/adapter.py`: defaults moved to `config.py`, mapping store and chat lock to `state.py` (the test patch point is now `upstream_bot.state`). Flows deliberately stay in one class.
- admin-web: shared kit/ui/charts/theme/types/useDialog moved to `src/shared/` (pure move, imports rewritten, tsc/eslint/vitest green).

##### r20 - audit follow-up (branch refactor/audit-r20-impl)
- admin-web PanelsView: the KPI strip, search/filter/sort toolbar and scope banner moved to PanelsToolbar.tsx (pure move, 638 to 562 lines). No behaviour change.
- Re-verified on a clean checkout: lint-imports 8 kept, ruff clean, mypy clean (371 files), admin-web tsc, eslint and vitest (42 files, 309 tests) green.
- Still open on purpose: remaining 500-600 line admin-web bodies (see docs/21-ROADMAP-TECHNICAL-DEBT.md debt register); rotate the GitHub token that was pasted into chat.

- r20 (2): ServerForm to ServerImport, UpstreamBotFields to UpstreamGuide and UpstreamEditors, TelegramLoginSettings to TelegramLoginParts, infra to InfraChain, ReportsView to ReportsSections (typed ReportModel props). Pure moves; typing ratchet lowered 2031 to 2029; tsc, eslint, vitest 309 and 210 UI contract tests green.

##### r21 - final verification (branch refactor/audit-r21-verified)
- Re-ran on the server from branch r20: lint-imports 8 kept, ruff clean (684 files), mypy clean (371 files), API suite 2728 passed / 1 skipped, admin-web tsc and eslint clean, vitest 309 passed (42 files). No code change; all audit items are implemented (see docs/21-ROADMAP-TECHNICAL-DEBT.md). Not run: real panels, Telegram bots, Playwright, restore drill.

##### Person account linking follow-up

- Re-authentication for sensitive linking changes: password if the account has one, else a single-use e-mail code (purpose identity_reauth, bound to the user id). Accounts with neither keep session proof plus the last-login-method guard: accepted for now because the access token is short-lived and a stronger proof (fresh Google sign-in or bot confirmation) would need a product call.
- Audit 13 and 14 stay as decided in r15/r17: bulk panel operations infrastructure-only, Telegram buttons in the system area.

### منبع / Source: `06-ARCHITECTURE-DECISIONS.md`

#### Melorin Change Log

Every change to the project (by anyone: owner, Claude, contractors) is recorded here,
newest first. Git history keeps the exact diff; this file keeps the *why*.

##### It fills itself - nobody has to remember

| Layer | What records the change | Who it covers |
|---|---|---|
| Code (this file) | `.github/workflows/changelog.yml` runs `scripts/changelog_auto.py` on **every push to `main`** and commits an entry for each commit that has none | anyone who pushes, aware of this log or not |
| Server (`var/ops-log.md`) | `scripts/ops_watch.sh` (cron, every 5 min) records new deployed commit, `.env` key changes (names only), hand-edited files, container restarts/crashes | anyone who touches the server |
| Server, deploys | `deploy.yml` writes success/failure with the commit | automatic deploys |
| Server, manual notes | `scripts/ops_log.sh` | people who want to add the *reason* |

Auto entries are honest: fields the author did not supply say "_not provided by the author_".
To make an entry complete without editing this file, put single-line trailers in the commit message
(`make setup-git` enables a template): `Area:`, `Before:`, `Problem:`, `Action:`, `After:`.
A commit that edits this file itself is considered already documented and is skipped.
Commits containing `[skip changelog]` and the bot's own commits are skipped.
If `main` is protected, allow `github-actions[bot]` to bypass so the bot can push the log.

> Entries before 2026-11-09 were archived (T-R12) and live in git tag `changelog-archive-2026-11-09` (`git show changelog-archive-2026-11-09:docs/06-ARCHITECTURE-DECISIONS.md`), per DOCUMENTATION-POLICY.

##### 2026-11-15 - Audit leftovers: whole-backend mypy, bulk split, infrastructure hub
- **Area:** api / admin-web / typing / docs
- **Before:** mypy gated 10 packages (about 235 errors elsewhere), `panelops/bulk.py` held lifecycle and worker in 690 lines, infrastructure had four menu entries with bulk runs apart from panel operations.
- **Problem:** the architecture audit (5.6, 8.4, 8.5) asked for staged typing, smaller files and one operations screen.
- **Action:** every remaining error fixed (annotations, host stubs for adapter mixins, `optional_ops`, guards that answer 404 instead of crashing); `bulk_runner.py` split off; menu is now «پنل‌ها و سرورها» / «پایش و سلامت» / «عملیات مدیریتی» (tabs ops + bulk). Decision: `docs/06-ARCHITECTURE-DECISIONS.md` (r16).
- **After:** `mypy` clean on the whole package; API behaviour unchanged except clean 404/401 answers on vanished-row paths.

##### 2026-11-15 - Pre-release audit: menu regroup, migrate service, web-kit lockfile
- **Area:** admin-web / compose / ci / docs
- **Before:** bulk panel operations sat under sales operations, manual tasks and Telegram buttons had menus that did not match their owner or permission, compose could start API/worker before the schema existed, web-kit had no lockfile.
- **Problem:** confusing admin menu and a fragile first start on a clean server, found by the architecture audit.
- **Action:** menu regrouped by job; manual tasks became the tab "اقدامات تکمیلی" of reseller applications; Telegram buttons moved to system settings; one-shot `migrate` compose service gating api/worker/backup; web-kit lockfile + CI audit; authFetch ratchet; two vulture false positives made explicit. Details: `docs/06-ARCHITECTURE-DECISIONS.md` (r13).
- **After:** fresh `docker compose up -d` migrates first; the menu mirrors the permission model. API behaviour is unchanged.

##### 2026-11-12 - Admin team: invite admins with roles to the web panel
- **Area:** api / admin-web / identity / docs
- **Before:** every admin-panel user was all-powerful and the only way to add one was the CLI bootstrap; there was no role, no invitation and no way to take access away.
- **Problem:** the owner could not give an accountant, a support agent or a viewer their own login without handing over everything.
- **Action:** roles (owner, manager, finance, support, viewer) over permission areas enforced server-side by a path->area table (`domain/admin_access.py`, unknown paths owner-only, empty role = no access); one-time hashed invite links (72h) where the invitee sets their own password and authenticator (`/auth/admin-invite/*`); owner screen "مدیران سامانه" (invite, change role, suspend, reset access, revoke sessions, remove) and "حساب من" for everyone; self-protection and last-owner protection; migration `0055_admin_team` back-fills existing admins as owner. Design: `docs/09-ADMIN-UI-ARCHITECTURE.md`.
- **After:** the owner can add admins from the panel with least-privilege roles; every denial is audited; existing admins keep full access.

##### 2026-11-12 - Persian Telegram alerts; first backup at install
- **Area:** infra / scripts / ops
- **Before:** Telegram alerts were Alertmanager's default English dump (labels, annotations, an internal Prometheus "Source:" link), and the critical `MelorinBackupStale` alert fired about 10 minutes after every install (no backup exists until the 02:00 UTC schedule), then "resolved" by itself.
- **Problem:** hard to read for an Iranian operator; a false critical alarm on every fresh install.
- **Action:** every rule in `infra/alerts.yml` has `summary_fa` and `hint_fa`; `alertmanager-entrypoint.sh` renders a Persian message template (severity, what happened, panel/server/job, hint, start/end in Iran time, no internal link; English summary is the fallback); `post_install.sh` takes the first backup immediately.
- **After:** one readable Persian message per alert group; no false backup alarm after install.

##### 2026-11-12 - HTTPS did not come up after repeated installs (Let's Encrypt rate limit); Redis overcommit
- **Area:** infra / scripts / ops
- **Before:** after several installs of the same domains the post-install check printed "did not answer 200 (got '000')" with no explanation, and the sites had no certificate.
- **Problem:** `melorin uninstall` ran `compose down -v`, which also deleted the `caddy_data` volume (certificates + ACME account), so every reinstall requested new certificates; Let's Encrypt allows 5 per exact hostname set per 7 days (HTTP 429, retry-after shown in the Caddy log). Caddy had no ACME e-mail, so its ZeroSSL fallback never registered. Redis warned that `vm.overcommit_memory` is 0.
- **Action:** Caddyfile sets `email` (from the admin e-mail, passed as `MELORIN_ACME_EMAIL`); uninstall now keeps the certificate volumes; `post_install.sh` explains why HTTPS fails (rate limit with retry time / port 80 unreachable / other issuance error), waits 60 s instead of 30 s, and sets `vm.overcommit_memory=1` persistently.
- **After:** a reinstall reuses the stored certificate. ZeroSSL refuses `.ir` hostnames, so for `.ir` the only CA is Let's Encrypt and an already exhausted limit can only be waited out.

##### 2026-11-11 - Installer wires the Telegram alert receiver; container logs are rotated
- **Area:** scripts / ops / docs
- **Before:** `install_server.sh` never set `ALERT_TELEGRAM_BOT_TOKEN` / `ALERT_TELEGRAM_CHAT_ID`; no service had a log-rotation policy.
- **Problem:** found on a clean-server install (T05/T06): Alertmanager started with "no alert receiver configured", so every Prometheus alert was dropped even though the bot token and the admin's Telegram ID had been given to the installer. Docker's default `json-file` driver never rotates, so logs could slowly fill the disk.
- **Action:** when both bot token and admin ID are supplied the installer now sets the two `ALERT_TELEGRAM_*` keys; `melorin` menu 1 (bot token) and 5 (admin ID) keep them in sync unless a separate alert bot was configured. `docker-compose.yml` gets an `x-logging` anchor (`json-file`, 10m x 3) on all 12 services. Reports: `docs/T05..T08`.
- **After:** verified live: Alertmanager loaded the receiver without the warning and delivered a test alert to the admin's Telegram (`alertmanager_notifications_total{integration="telegram"}` = 1, all failure counters 0); `docker compose config` valid, `scripts/check_ops_p0.py` green; all 12 containers healthy after recreation with `max-size=10m, max-file=3`.

##### 2026-11-09 - Panel backup verification works against a newer panel PostgreSQL
- **Area:** scripts / docs / ops
- **Before:** `scripts/verify_panel_backup.sh` always called the host's `pg_restore`.
- **Problem:** found live on the test host: the panel database is PostgreSQL 17, Ubuntu 24.04 ships `pg_restore` 16, so the check of a perfectly good archive failed with `unsupported version (1.16) in file header`.
- **Action:** optional `PG_RESTORE` (a command, e.g. `docker exec -i pasarguard-timescaledb-1 pg_restore`); the dump is read from stdin; a failure prints pg_restore's message plus a hint. Default behaviour is unchanged. RUNBOOK step 6 documents it.
- **After:** the latest real archive verified on the test host: checksum OK, age decrypt OK, 330 database objects, 9 data entries (certs included). Prometheus checked live after the `nobody` chown: target `up`, 4 rule groups / 21 rules, `melorin_panel_nodes` returns data.

##### 2026-11-09 - PG-12: the store role name is the admin's choice; PG-05 proven on the live panel
- **Area:** api / tests / docs / ops
- **Before:** the store role was the fixed name `melorin-store`; `applied_role()` only recognised that exact name. PG-05 provision/rotate had never been run against a real panel.
- **Problem:** a store (or another deployment) may need its own role name; and "verified on fakes" is not "verified live".
- **Action:** `store_role.normalize_role_name` (default `melorin-store`; 2-32 chars `a-z 0-9 - _`; `owner`, `administrator`, `operator`, `melorin-service` refused, validated BEFORE any panel call). `apply {role_name}` creates that role and records `panel.config.admin_role` + `admin_role_managed`; `plan?role_name=` previews it; `revert` clears both. Admin-web/API client regenerated (`StoreRoleIn.role_name`). Live on the test panel (5.6.0): `rotate` run with a temporary owner key (created and deleted by the operator, never stored) - new service key verified as `melorin-service` before the switch, old key deleted, a stray service key left by an earlier attempt found and removed, panel health read with the new key.
- **After:** 127 tests of the affected area green (SQLite lane, run from the source tree); `gen_docs --check` clean; api-client typecheck + tests green.

##### 2026-11-09 - Live proof on the test panel: three bugs only a real panel showed, branding verified end to end, panel backup complete
- **Area:** api / tests / docs / ops
- **Before:** PG-05, the `melorin-store` role, branding and the panel backup were verified on fakes only; the docs said "existing admins change on their next sync" and "unverified: how `custom_variables` reach the page".
- **Problem:** (1) `sync_all` only re-pushes unfinished rows and `ensure_admin` never sent `role_id`, so an admin that already existed never got the new role; (2) the service role lacked `admin_roles.read_simple` (403 on the role lookup); (3) rotate sent `token_urlsafe(32)` as the service admin's password, which the panel's password rule refuses when it has no special character (422, random); (4) the backup could not read the panel's `privkey.pem` (root, 0600) as the worker's non-root user.
- **Action:** `ensure_admin` moves an existing admin to the wanted role (never an owner); `store_role.apply/revert` flag the panel's admin rows for the next sync; `admin_roles.read_simple` added to the single capability table; service admin password built with `generate_password()`; ACL for uid 10001 on the panel cert directory (operator step, RUNBOOK). Live results: `ml_main` now holds `melorin-store` on the panel; rotate works repeatedly; branding applied for a test store -> a test user's subscription page shows brand name, support link and logo (so `user.admin.custom_variables` is the right path; the template needed no change); then reverted and the test user deleted. Panel backup now holds database + certs + templates (195 KB) and `verify_panel_backup.sh` passed (330 DB objects, 9 data entries).
- **After:** affected tests green (new: role move, owner untouched, password rule, flagged rows); ruff clean; temporary owner keys created for the proof were deleted; the old owner key `bot` is still active on the panel (revoke it there).

##### 2026-11-09 - Mediator rework: verification pass (layering contract, near-expiry warning, formatting)
- **Area:** api / worker / tests / docs
- **Before:** `import-linter` reported the layers contract BROKEN on this branch (`vpn.manual_assign` imported `catalog.service`); `near_expiry_job` warned from Melorin's sold expiry alone, so an `on_hold` account (clock not started) or an account renewed on the panel could get a wrong "ends soon" notice; four PG-12 files were not `ruff format`-clean.
- **Problem:** the sold expiry is Melorin's entitlement, not the panel's "now"; a warning is a statement about "now".
- **Action:** `product_snapshot` moved to `domain/product_snapshot.py` (pure; `catalog` and `vpn` both use it, 6/6 contracts kept). `near_expiry_job` now nominates candidates from the sold expiry and sends only after a live read says the panel agrees (not `on_hold`, panel expiry inside the window); a panel that does not answer sends nothing and leaves the flag unset so the next run retries; accounts without a panel keep the sold expiry. New test `test_near_expiry_warning_is_sent_only_when_the_panel_agrees`. Formatting fixed.
- **After:** verified on this branch: backend suite 2319 passed / 10 skipped; mediator, live-view, manual-assign, connections and PostgreSQL concurrency tests also green on PostgreSQL 16; `alembic upgrade tip` -> `downgrade 0050` -> `upgrade head` -> `alembic check` clean; `ruff check`/`format` clean; admin-web 212 and store-web 76 vitest tests pass, both lint (0 errors) and admin-web build pass.

##### 2026-11-09 - PG-12: vetted base subscription template that reads the `melorin_*` variables
- **Area:** infra / docs / tests
- **Before:** branding values were written into the store admin's `custom_variables`, but nothing in the repo could display them.
- **Problem:** without an installed page template the "apply to panel" step changes nothing a customer sees. PasarGuard's docs say the subscription page is built from the admin's `sub_template` or the default template (Jinja) but do not say how `custom_variables` reach a template.
- **Action:** `infra/sub-template/index.html`: one fixed, operator-installed page (no script, no external request, CSP `default-src 'none'`, every value escaped with `|e`, only https/tg links and https logo accepted, neutral page when variables are absent). It tries `admin.custom_variables` and `custom_variables`. Melorin still never writes `sub_template` or HTML. `tests/test_sub_template.py` renders it with an escaping-off Jinja environment (worst case).
- **After:** 5 new tests pass. STILL UNVERIFIED on a live panel: under which name the panel exposes `custom_variables` to the template; the first apply on a test store must confirm it, and the template line that reads them must be adjusted if not.

##### 2026-11-09 - PG-12: screens for store usage report and subscription branding (store-web, admin-web)
- **Area:** store-web / admin-web / tests
- **Before:** the usage-report API (`/reseller/usage-report`), the branding fields API (`/reseller/sub-branding`) and the admin apply/revert API existed, but no web screen used them; only the reseller bot showed the usage report.
- **Problem:** a store owner on the site could not see usage or set the subscription-page brand, and the admin had no button for the audited "apply to panel" step.
- **Action:** store-web: new tab "گزارش مصرف" (`ResellerUsage.jsx`: live summary, 5 top consumers, "temporarily unavailable" and no numbers when the panel does not answer, never IP/links) and a branding form under "ادمین پنل" (`ResellerSubBranding.jsx`: name, support link, logo; saves only changed fields, nothing is sent to a panel). admin-web: `SubBrandingCard.jsx` in the panel-admin drawer (shows wanted vs on-panel, apply/remove only after typing the panel name, disabled while the panel is unreachable). No backend change.
- **After:** 4 new store-web tests (76 total) and 3 new admin-web tests (212 total) pass; the 26 backend tests of both features pass. The panel's page template reading `melorin_*` variables is still unverified on a live panel (PasarGuard docs do not describe it).

##### Entry template

```
### YYYY-MM-DD HH:MM UTC - <who> - <area>
- **Before:** state/behaviour before the change
- **Problem:** the bug, error or missing piece (with error text / evidence)
- **Action:** what was changed to fix it (files, commands)
- **After:** verified result (tests run, health check, screenshot)
- **Ref:** commit hash / PR
```

Never write secrets (tokens, passwords, keys, `.env` values) in this file.

---

<!-- AUTO-ENTRIES-BELOW (newest first) -->

###### 2026-11-09 - Claude (with owner) - PG-12 per-store subscription branding
- **Before:** every store's subscription page carried the shared panel branding; `stores.branding` was free-form JSON replaced wholesale by the owner patch.
- **Problem:** a reseller could not show its own name, support link or logo; a free-form value that a panel page may print is an injection risk.
- **Action:** `modules/vpn_accounts/sub_branding.py` (validated fields in `stores.branding["sub"]`; admin `preview` / `apply` / `revert` writing three `custom_variables` keys of the store's panel admin, other keys kept, read-back verified with restore, typed panel name, audited without values); owner `GET/PUT /stores/{id}/reseller/sub-branding`; the generic branding patch can no longer set or wipe `sub`/`sub_applied`; adapter `read_custom_variables` / `write_custom_variables`; no `sub_template`, no HTML from stores.
- **After:** `tests/test_sub_branding.py` (9 tests) and the 5.6.0 contract replay pass. No migration. NOT run against a live panel; how the panel page reads `custom_variables` is unconfirmed.
- **Ref:** this commit

### منبع / Source: `06-ARCHITECTURE-DECISIONS.md`

#### History

All former phase reports, completion notes and audits are preserved in git under the annotated tag
**`docs-history-2026-10-22`** (the commit just before they were removed from the working tree). They are
evidence of what changed and why - **never current status or release approval** (see `docs/STATUS.md` and
`docs/20-TESTING-QUALITY-RELEASE.md`).

Read one:

```bash
git show docs-history-2026-10-22:docs/history/<file>
git ls-tree --name-only docs-history-2026-10-22 docs/history/    # list them all
git checkout docs-history-2026-10-22 -- docs/history/<file>        # restore one temporarily
```

The same tag also holds the pre-merge document set (separate EN/FA setup guides, `API-ROUTES-ACTIVE.md`, `API-IMPLEMENTATION.md`,
`12-Change-Log-v1.1.md`, `15-Store-Isolation-Rollout.md`, `RUNTIME-EVIDENCE.md`, `TELEGRAM-SCOPE.md`, `BACKUP-IMPLEMENTATION.md`,
`INFRA_REDESIGN_FA.md`, `RESELLER_BOT_DESIGN_FA.md`, `FULL_PROJECT_AUDIT.md`, `DOCUMENTATION-STATUS.md`).

##### Kept in `docs/history/` because tests and guards read them

| File | Title |
|---|---|
| [`06-ARCHITECTURE-DECISIONS.md`](history/I33_DOCUMENTATION_STATUS.md) | I33: documentation status policy |
| [`06-ARCHITECTURE-DECISIONS.md`](history/I39_IRT_IRR_AUDIT.md) | I39: IRT/IRR compatibility audit |
| [`15-PAYMENTS-WALLET-FINANCE.md`](history/I40_CURRENCY_PAYMENT_CONTRACT.md) | I40: currency/payment contract |
| [`18-OPERATIONS-DEPLOYMENT-DR.md`](history/I41_BACKUP_RESTORE_DRILL.md) | I41: backup and restore drill |

##### Index of the 84 reports now only in the tag

###### I - infrastructure / hardening passes (I17-I66) (45)

| File | Title |
|---|---|
| `I17_BOOTSTRAP.md` | I17: first-install bootstrap |
| `I18_WORKER_MODEL_REGISTRATION.md` | I18: worker model registration |
| `I19_OUTBOX_SESSION_SAFETY.md` | I19: outbox session safety and replay protection |
| `I20_ARQ_SCHEDULER.md` | I20: reliable ARQ polling |
| `I21_WEB_LOCKFILES.md` | I21: Web dependency lockfiles |
| `I22_CI_QUALITY_GATE.md` | I22: CI quality gate |
| `I23_WORKER_ADAPTER_IMPORT.md` | I23: worker adapter registry import |
| `I24_SSRF_GUARD.md` | I24: webhook SSRF guard |
| `I25_RATE_LIMIT_HARDENING.md` | I25: rate-limit and login throttling |
| `I26_OPERATIONAL_ENDPOINTS.md` | I26: operational endpoint exposure |
| `I27_ASYNC_INTEGRATION_TESTS.md` | I27: async and integration test depth |
| `I28_LINT_GATE.md` | I28: lint gate cleanup |
| `I29_FRONTEND_RUNTIME_DATA.md` | I29: frontend runtime data |
| `I30_TOKEN_STORAGE.md` | I30: browser token storage |
| `I31_READINESS_OBSERVABILITY.md` | I31: readiness and worker observability |
| `I32_SINGLE_WORKER_ENTRYPOINT.md` | I32: single worker entrypoint |
| `I34_EXTERNAL_INTEGRATIONS.md` | I34: external integration smoke gate |
| `I35_TEST_MATRIX.md` | I35: test matrix and runtime evidence |
| `I36_OPERATIONS_CLI.md` | I36: operations CLI |
| `I37_PRIVACY_RETENTION.md` | I37: privacy retention job |
| `I38_PGCLOCK_GATEWAYS_IRT.md` | PGClockBot payment destination integration |
| `I42_ADMIN_FRONTEND_AUTH.md` | I42 — Admin frontend auth/runtime fix |
| `I43_SANAEI_3XUI_ADAPTER.md` | I43 — تکمیل Adapter پنل سنایی (3x-ui) |
| `I45_J01_DEPENDENCY_HARDENING.md` | I45: J01 Dependency Hardening |
| `I46_J02_TRUSTED_PROXY_CIDR.md` | I46: J02 Trusted Proxy CIDR Handling |
| `I47_J03_IDEMPOTENCY_RACE.md` | I47: J03 Concurrent Idempotency-Key Requests |
| `I48_STORE_SCOPED_RESELLERS.md` | I48: Store-Scoped Reseller Model |
| `I49_J04_ENVIRONMENT_SAFETY.md` | I49: J04 Environment Safety |
| `I50_J05_TEST_STRATEGY.md` | I50: J05 Test Strategy and Coverage Gate |
| `I51_J06_STAGING_EVIDENCE.md` | I51: J06 Staging Evidence Gate |
| `I52_J07_REDIS_RATE_LIMIT_POLICY.md` | I52: J07 Redis Outage Rate-Limit Policy |
| `I53_J08_READINESS_HEALTHCHECKS.md` | I53: J08 Readiness Semantics and Healthchecks |
| `I54_J09_OPERATIONAL_ENDPOINT_AUTH.md` | I54: J09 Operational Endpoint Authentication |
| `I55_J10_ASYNC_PASSWORD_KDF.md` | I55: J10 Async Password KDF |
| `I56_J11_ADMIN_SECURITY.md` | I56: J11 Admin Security |
| `I57_J12_FIXED_PAYMENT_CALLBACK_ORIGIN.md` | I57: J12 Fixed Payment Callback Origin |
| `I58_J13_FRONTEND_DEPENDENCY_HARDENING.md` | I58: J13 Frontend Dependency Hardening |
| `I59_J14_REPORTS_REFERRALS.md` | I59: Reports and Referral Modules |
| `I60_J15_MULTI_STORE_RESELLER_BOTS.md` | I60: J15 Multi-Store Reseller Bots |
| `I61_BOT_STORE_OWNER_MAPPING.md` | I61: Bot, Store, Owner Mapping |
| `I62_J16_OBSERVABILITY_ALERTING.md` | I62: Observability and Alerting |
| `I63_J17_EXPLICIT_CORS_POLICY.md` | I63: J17 Explicit CORS Policy |
| `I64_J18_HTTPONLY_ADMIN_SESSION.md` | I64: J18 HttpOnly Admin Session |
| `I65_J19_QUALITY_GATE_HARDENING.md` | I65: J19 Quality Gate Hardening |
| `I66_J20_DOCUMENTATION_CONSOLIDATION.md` | I66: J20 Documentation Consolidation |

###### F / H / CI - finding and completion reports (37)

| File | Title |
|---|---|
| `Melorin_Admin_Web_Completion_FA.md` | تکمیل اجزای پنل Admin Web |
| `Melorin_CI_Execution_EN.md` | Melorin CI Execution |
| `Melorin_CI_Execution_FA.md` | اجرای CI ملورین |
| `Melorin_F001-F005_Refresh_FA.md` | بازبینی نهایی F001 تا F005 |
| `Melorin_F001-F010_Completion_EN.md` | Melorin F001-F010 Completion |
| `Melorin_F001-F010_Completion_FA.md` | تکمیل F001 تا F010 ملورین |
| `Melorin_F001-F010_Final_EN.md` | Melorin F001-F010 Final Completion |
| `Melorin_F001-F010_Final_FA.md` | تکمیل نهایی F001 تا F010 ملورین |
| `Melorin_F002-F005_Completion_EN.md` | Melorin F002-F005 Completion |
| `Melorin_F002-F005_Completion_FA.md` | تکمیل F002 تا F005 ملورین |
| `Melorin_F005-F008_Completion_FA.md` | تکمیل F005 تا F008 ملورین |
| `Melorin_F007-F010_Completion_FA.md` | تکمیل F007 تا F010 ملورین |
| `Melorin_F010-F013_Completion_FA.md` | تکمیل F010 تا F013 ملورین |
| `Melorin_F010-F015_Completion_EN.md` | Melorin F010-F015 Completion |
| `Melorin_F010-F015_Completion_FA.md` | تکمیل F010 تا F015 ملورین |
| `Melorin_F015-F018_Completion_FA.md` | تکمیل F015 تا F018 ملورین |
| `Melorin_F015-F038_Final_Completion_FA.md` | Melorin F015-F038 Final Completion |
| `Melorin_F019-F021_Completion_FA.md` | تکمیل F019 تا F021 ملورین |
| `Melorin_F021-F023_Completion_FA.md` | تکمیل F021 تا F023 ملورین |
| `Melorin_F024-F026_Completion_FA.md` | تکمیل F024 تا F026 ملورین |
| `Melorin_F026-F032_Completion_FA.md` | تکمیل F026 تا F032 ملورین |
| `Melorin_F027-F030_Completion_FA.md` | تکمیل F027 تا F030 ملورین |
| `Melorin_F031-F033_Completion_FA.md` | تکمیل F031 تا F033 ملورین |
| `Melorin_F033-F038_Completion_FA.md` | تکمیل F033 تا F038 ملورین |
| `Melorin_H001_Completion_FA.md` | تکمیل H001: نصب و پیش‌نیازهای اجرای واقعی |
| `Melorin_H002_Completion_FA.md` | تکمیل H002: explicit Alembic baseline |
| `Melorin_H003_Completion_FA.md` | تکمیل H003: اتصال واقعی وضعیت Backup به Admin Web |
| `Melorin_H004_Completion_FA.md` | تکمیل H004: reproducible Web dependencies |
| `Melorin_H005_Completion_FA.md` | تکمیل نهایی H005: Telegram runner واقعی |
| `Melorin_H006_Completion_FA.md` | تکمیل H006: refund واقعی پرداخت |
| `Melorin_H007_Completion_FA.md` | تکمیل H007: backup orchestration و restore evidence boundary |
| `Melorin_H008_Completion_FA.md` | تکمیل H008: provider/panel و DNS runtime boundaries |
| `Melorin_H009_Completion_FA.md` | تکمیل H009: صحت مالی و concurrency evidence |
| `Melorin_H010_Completion_FA.md` | تکمیل H010: Observability عملیاتی |
| `Melorin_H011_Completion_FA.md` | تکمیل H011: release evidence matrix و یکپارچه‌سازی مستندات |
| `Melorin_H012_Completion_FA.md` | تکمیل H012: quality gate و test/contract suite |
| `Melorin_Website_Completion_FA.md` | تکمیل بخش وبسایت Melorin |

###### Audits and reviews (2)

| File | Title |
|---|---|
| `FINAL_IMPLEMENTATION_REPORT.md` | Melorin Comprehensive Implementation Report |
| `REVIEW_CHANGES_2026-10-12.md` | Comprehensive review changes - 2026-10-12 |

### منبع / Source: `history/I33_DOCUMENTATION_STATUS.md`

#### I33: documentation status policy

The release evidence matrix is the single source of current release status.
Phase and finding completion reports remain useful historical records, but
cannot imply runtime or production approval.

The policy is enforced by the release-matrix checker and documented in both
the matrix and the project README. New implementation work must land in source
and tests first, then update the canonical evidence record.

### منبع / Source: `history/I39_IRT_IRR_AUDIT.md`

#### I39: IRT/IRR compatibility audit

The currency boundary is now explicit:

- **IRT** is the user-facing default for new stores, wallets, products, and
  concurrency smoke data.
- **IRR** remains supported only when a Store or legacy record explicitly uses
  it.
- Wallet, ledger, order, payment, coupon, commission, and reseller operations
  continue to require exact currency matching. No implicit application-level
  conversion is allowed.
- Zarinpal converts IRT to rial at the adapter edge only, using `amount * 10`
  for request/verify, while Melorin records the original IRT amount and
  currency.

Existing IRR records are not rewritten. A migration or financial reconciliation
is required before changing any existing Store currency. Provider sandbox
verification is still required before release.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
