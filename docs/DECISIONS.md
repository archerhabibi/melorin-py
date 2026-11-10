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
- Decision: `sanaei`, `pasarguard` and `upstream_bot` all stay. None is removed; each is a provider adapter declared in `modules/vpn/adapters/providers.py` (`ProviderSpec`: label, transport, features, target kinds, adapter path, contract path).
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
- Source-contract guards (`check_g001_g010.py`, `check_frontend_contracts.py`, `tests/_source.read_store_shell`) read the storefront shell as App.jsx + the split files, so a guard cannot pass by looking at only half the code. First-load budget for store-web raised 272 -> 273 kB for the extra component boundaries.
- Still open: admin-web has no TypeScript yet; `App` still owns session/catalog state (a `useSession` / `useCatalog` hook extraction is the next safe step, now covered by the browser specs).

## T-R11 step 2: session and catalog hooks (2026-11-10)
- `useCoreFetch` (authenticated fetch + one silent refresh) and `useStoreCatalog` (store, bundles, packages) moved out of `App`; `App.jsx` is ~470 lines.
- The first attempt put the hook calls after a line that already used `hasBot`: lint, vitest (jsdom) and `vite build` all passed, but the real browser showed a white screen (`Cannot access ... before initialization`). The Playwright specs caught it; fixed by calling the hooks before first use. Lesson: for `App` refactors the browser specs are the gate, not vitest.
