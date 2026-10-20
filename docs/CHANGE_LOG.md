# Melorin Change Log

Every change to the project (by anyone: owner, Claude, contractors) is recorded here,
newest first. Git history keeps the exact diff; this file keeps the *why*.

## It fills itself - nobody has to remember

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

## Entry template

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

### 2026-10-20 03:00 UTC - Claude - api, tests, store-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** refactor(inquiry): all scoping, search and reseller renewal live in Core (vpn/inquiry service layer); Core supplies rule texts, channels only display
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (14):** `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/reseller/router.py`, `apps/api/melorin/modules/reseller/schemas.py`, `apps/api/melorin/modules/vpn/inquiry.py`, `apps/api/melorin/modules/vpn/router.py`, `apps/api/melorin/modules/vpn/schemas.py`, `apps/api/tests/test_q01_account_inquiry.py`, `apps/api/tests/test_q02_bot_inquiry.py` (+6 more)
- **Ref:** `e649e6b`

### 2026-10-20 02:52 UTC - Claude - api, tests, store-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(inquiry): reseller list = own accounts only, search reaches own customers; reseller renews own + own customers' accounts (Core + bots + site)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (11):** `apps/api/melorin/modules/reseller/router.py`, `apps/api/melorin/modules/vpn/inquiry.py`, `apps/api/melorin/modules/vpn/schemas.py`, `apps/api/tests/test_q01_account_inquiry.py`, `apps/api/tests/test_q02_bot_inquiry.py`, `apps/api/tests/test_renewal_core.py`, `apps/store-web/src/AccountInquiry.jsx`, `apps/store-web/src/Reseller.jsx` (+3 more)
- **Ref:** `3cccd95`

### 2026-10-19 21:15 UTC - Claude - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(inquiry): searchable, paged admin account inquiry (platform owner) + search box in admin-web
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (6):** `apps/admin-web/src/AdminSections.jsx`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/vpn/inquiry.py`, `apps/api/tests/test_q01_account_inquiry.py`, `apps/api/tests/test_q02_bot_inquiry.py`, `docs/13-Renewal-Core-Design.md`
- **Ref:** `0443bae`

### 2026-10-19 21:11 UTC - renewal-design - tests, store-web, bot  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(inquiry): redesigned account inquiry/renewal UI in main+reseller bots and store website (customer + store owner)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (9):** `apps/api/tests/test_q02_bot_inquiry.py`, `apps/api/tests/test_telegram_ux_v2.py`, `apps/store-web/src/AccountInquiry.jsx`, `apps/store-web/src/Dashboard.jsx`, `apps/store-web/src/Reseller.jsx`, `apps/store-web/src/Subscription.jsx`, `apps/telegram-main/runner.py`, `apps/telegram-reseller/runner.py` (+1 more)
- **Ref:** `e4052cd`

### 2026-10-19 21:11 UTC - Claude - api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(inquiry): filter chips, counters and live panel refresh (customer + store owner)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (4):** `apps/api/melorin/modules/reseller/router.py`, `apps/api/melorin/modules/vpn/inquiry.py`, `apps/api/melorin/modules/vpn/router.py`, `apps/api/tests/test_q01_account_inquiry.py`
- **Ref:** `39d9598`

### 2026-10-19 21:11 UTC - Claude - api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(inquiry): searchable, paged account inquiry; owner-scoped store accounts API
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (6):** `apps/api/melorin/app.py`, `apps/api/melorin/modules/reseller/router.py`, `apps/api/melorin/modules/vpn/inquiry.py`, `apps/api/melorin/modules/vpn/router.py`, `apps/api/melorin/modules/vpn/schemas.py`, `apps/api/tests/test_q01_account_inquiry.py`
- **Ref:** `fe6427e`


### 2026-10-19 11:11 UTC - Claude - api, tests, store-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(renewal): core-owned renewal (10-day window, package reset, current bundle price) - - new vpn/renewal.py: eligibility window, target, apply_to_panel (reset usage), landed() - orders.create_order: renewal via core rules, product must equal account's, no parallel renewals - allocation: renewal o…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (19):** `apps/api/melorin/modules/catalog/router.py`, `apps/api/melorin/modules/catalog/schemas.py`, `apps/api/melorin/modules/orders/service.py`, `apps/api/melorin/modules/vpn/adapters/base.py`, `apps/api/melorin/modules/vpn/adapters/mock.py`, `apps/api/melorin/modules/vpn/allocation.py`, `apps/api/melorin/modules/vpn/renewal.py`, `apps/api/melorin/modules/vpn/router.py` (+11 more)
- **Ref:** `5c29782`


### 2026-10-19 10:02 UTC - archerhabibi - ci, scripts  _(auto)_
- **Before:** CI red on main for several runs
- **Problem:** secrets guard false positives, cwd-relative guard scripts, alembic check on an unmigrated DB, wrong smoke script path/imports/FK rows, format drift
- **Action:** see PR description
- **After:** quality + postgres-lane green
- **Files (11):** `.github/workflows/ci.yml`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/wallet/models.py`, `apps/api/tests/test_k01_optional_integrations.py`, `apps/api/tests/test_m73_runtime_evidence.py`, `apps/api/tests/test_r01_telegram_login_settings.py`, `apps/api/tests/test_reseller_wallet_merge_migration.py`, `apps/api/tests/test_s01_identity_reviews.py` (+3 more)
- **Ref:** `95cd9d9`


### 2026-10-19 07:06 UTC - archerhabibi - orders/delivery, vpn API, store-web  _(auto)_
- **Before:** purchase result had no link/QR in web; Telegram post could go out without link/QR
- **Problem:** customers did not reliably receive link and QR together
- **Action:** QR endpoint, LinkNotReady retry (1h fallback to text), PurchaseResult/SubscriptionCard UI, review fixes
- **After:** 826 unit tests pass, ruff check clean, store-web build OK
- **Files (7):** `apps/api/melorin/modules/orders/delivery.py`, `apps/api/melorin/modules/vpn/router.py`, `apps/api/tests/test_order_delivery_post.py`, `apps/api/tests/test_vpn_qr_endpoint.py`, `apps/store-web/src/App.jsx`, `apps/store-web/src/Dashboard.jsx`, `apps/store-web/src/Subscription.jsx`
- **Ref:** `ab29b1c`


### 2026-10-19 05:11 UTC - archerhabibi - admin-web, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(reseller): use the owner's ordinary Main Store wallet for reseller costs (#21) - A reseller now uses the very same wallet they already had as a customer in Main Store; the only addition is ResellerProfile.debt_limit, which lets reseller costs (not the owner's own purchases) take that wallet do…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (12):** `apps/admin-web/src/ResellerApplicationsView.jsx`, `apps/admin-web/src/ResellersView.jsx`, `apps/api/alembic/versions/0026_merge_reseller_credit_wallets.py`, `apps/api/melorin/modules/orders/service.py`, `apps/api/melorin/modules/reseller/router.py`, `apps/api/melorin/modules/wallet/models.py`, `apps/api/tests/test_m71_order_money_db.py`, `apps/api/tests/test_reseller_purchase_flow.py` (+4 more)
- **Ref:** `451421f`


### 2026-10-19 03:39 UTC - Claude - api  _(auto)_
- **Before:** when a reseller store could not cover its cost (debt_limit 0 with no credit, or limit reached), POST /stores/{id}/orders crashed with MissingGreenlet (HTTP 500). The Telegram bot treats 5xx as transient and keeps retrying the update, the store website only showed a generic "order failed", so resell…
- **Problem:** create_order called session.rollback() and then read store.id; rollback expires every ORM instance and async code cannot lazy-load them. The idempotency-recovery queries after a rollback had the same pattern (store.id / user.id).
- **Action:** capture store_id/user_id as plain values at the top of create_order and use them in every recovery path; notify_debt_reached now accepts a store id.
- **After:** new tests/test_reseller_purchase_flow.py (happy path, debt_limit 0, limit reached, credit covers cost) - the two debt-limit tests fail with MissingGreenlet on the old code; full suite 818 passed, ruff clean.
- **Files (2):** `apps/api/melorin/modules/orders/service.py`, `apps/api/tests/test_reseller_purchase_flow.py`
- **Ref:** `8ce9134`


### 2026-10-18 17:08 UTC - archerhabibi - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(identity): redesign identity review screen in admin panel and Telegram bot - - admin-web: new IdentityReviewsView (KPI bar, filters, side-by-side account cards, detail drawer with note, reopen) - api: enriched /identity-link-reviews (status=all, source_user, candidates), optional note on dismi…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (5):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/IdentityReviewsView.jsx`, `apps/api/melorin/modules/admin/router.py`, `apps/api/tests/test_s01_identity_reviews.py`, `apps/telegram-main/runner.py`
- **Ref:** `233005c`


### 2026-10-18 13:43 UTC - Claude - admin-web, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(admin-web): redesign Payments screen (review queue, KPIs, filters, detail drawer, gateway settings); update contract test for new location
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (4):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/PaymentsView.jsx`, `apps/admin-web/src/styles.css`, `apps/api/tests/test_wallet_payment_regressions.py`
- **Ref:** `570316b`


### 2026-10-18 11:13 UTC - Claude - api, tests, docs  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(M7.6): observability - HTTP latency histogram, bounded route labels, DB-derived payment/provisioning/reseller-bot/backup gauges, 6 new alert rules, tests
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (9):** `apps/api/melorin/app.py`, `apps/api/melorin/core/business_metrics.py`, `apps/api/melorin/core/metrics.py`, `apps/api/melorin/core/middleware.py`, `apps/api/tests/test_m71_payments_service_db.py`, `apps/api/tests/test_m76_observability.py`, `apps/api/tests/test_m77_postgres_concurrency.py`, `docs/08-Operations-DR.md` (+1 more)
- **Ref:** `0b3a0d8`

### 2026-10-18 11:10 UTC - Claude - ci-deploy, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** test(M7.7): PostgreSQL-backed test lane (TEST_PG_URL, schema per test), PG concurrency tests, CI job postgres-lane; fix duplicate bot_store_bindings index declaration
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (7):** `.github/workflows/ci.yml`, `apps/api/melorin/modules/stores/models.py`, `apps/api/tests/_db.py`, `apps/api/tests/test_m71_payments_service_db.py`, `apps/api/tests/test_m71_provisioning_db.py`, `apps/api/tests/test_m77_postgres_concurrency.py`, `docs/09-Testing.md`
- **Ref:** `41db3eb`

### 2026-10-18 07:07 UTC - archerhabibi - other, tests, docs  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(M7.3): fail-closed runtime evidence collector (Telegram, Zarinpal sandbox, panels, Docker, Caddy TLS gate, Prometheus/Alertmanager) + runbook; matrix points at it
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (6):** `Makefile`, `apps/api/tests/test_m73_runtime_evidence.py`, `docs/RELEASE-EVIDENCE-MATRIX.md`, `docs/RUNTIME-EVIDENCE.md`, `scripts/check_release_matrix.py`, `scripts/runtime_evidence.py`
- **Ref:** `160b0e8`

### 2026-10-18 07:04 UTC - archerhabibi - api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** test(M7.2): PasarGuard + Zarinpal adapter contract tests; fix PasarGuard create_account (_req called without HTTP method) and fail closed on missing Zarinpal Authority
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (4):** `apps/api/melorin/modules/payments/adapters/zarinpal.py`, `apps/api/melorin/modules/vpn/adapters/pasarguard.py`, `apps/api/tests/test_m72_pasarguard_adapter_contract.py`, `apps/api/tests/test_m72_zarinpal_adapter_contract.py`
- **Ref:** `3796a17`

### 2026-10-18 07:01 UTC - archerhabibi - ci-deploy, other, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** test(M7.1): money-path tests (payments, wallet ledger, orders/refund, provisioning, coupon/commission); coverage gate 20 -> 60
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (9):** `.github/workflows/ci.yml`, `.gitignore`, `apps/api/tests/_db.py`, `apps/api/tests/test_j05_test_strategy.py`, `apps/api/tests/test_m71_domain_money_rules.py`, `apps/api/tests/test_m71_order_money_db.py`, `apps/api/tests/test_m71_payments_service_db.py`, `apps/api/tests/test_m71_provisioning_db.py` (+1 more)
- **Ref:** `494f1de`


### 2026-10-18 06:39 UTC - Melorin M6 - other  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** chore(M6.8): ignore frontend build output (apps/*/dist)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `.gitignore`
- **Ref:** `f80820b`

### 2026-10-18 06:38 UTC - Melorin M6 - tests, store-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** test(M6.8): frontend dependency contract follows Tailwind 4 (@tailwindcss/vite); README
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (2):** `apps/api/tests/test_j13_frontend_dependencies.py`, `apps/store-web/README.md`
- **Ref:** `e4ff1b8`

### 2026-10-18 06:37 UTC - Melorin M6 - store-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** build(M6.8b): store-web -> Vite 7 + Tailwind 4 (npm audit clean) - - vite 7.3.7, @vitejs/plugin-react 5.2.0, tailwindcss 4.3.3 via @tailwindcss/vite - tailwind.config.js moved to CSS @theme (colors, font, shadows, radius); derived .btn-* classes no longer @apply a component class (unsupported in v4…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (7):** `apps/store-web/Dockerfile`, `apps/store-web/package-lock.json`, `apps/store-web/package.json`, `apps/store-web/postcss.config.js`, `apps/store-web/src/styles.css`, `apps/store-web/tailwind.config.js`, `apps/store-web/vite.config.js`
- **Ref:** `2a0661a`

### 2026-10-18 06:36 UTC - Melorin M6 - admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** fix(M6.8a): Tailwind 4 renamed utilities and pointer cursor parity in admin-web
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (7):** `apps/admin-web/src/AdminSections.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/TicketsView.jsx`, `apps/admin-web/src/Trend.jsx`, `apps/admin-web/src/palette.jsx`, `apps/admin-web/src/styles.css`
- **Ref:** `b700312`

### 2026-10-18 06:35 UTC - Melorin M6 - admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** build(M6.8a): admin-web -> Vite 7 + Tailwind 4 (npm audit clean) - - vite 5.4.21 -> 7.3.7, @vitejs/plugin-react 4.3.1 -> 5.2.0 - tailwindcss 3.4.14 -> 4.3.3 via @tailwindcss/vite; CSS-first config (dark variant on [data-theme=dark]); drop tailwind/postcss configs - Dockerfile node 20 -> 22 (Vite 7 …
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (7):** `apps/admin-web/Dockerfile`, `apps/admin-web/package-lock.json`, `apps/admin-web/package.json`, `apps/admin-web/postcss.config.js`, `apps/admin-web/src/styles.css`, `apps/admin-web/tailwind.config.js`, `apps/admin-web/vite.config.js`
- **Ref:** `0511851`

### 2026-10-18 06:26 UTC - Melorin M6 - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** fix(M6.9): reports API consistency (404, typed id, date filter, pagination, sold-orders series, tz-aware days)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (6):** `apps/admin-web/src/Trend.jsx`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/admin/timeseries.py`, `apps/api/melorin/modules/reports/router.py`, `apps/api/requirements.txt`, `apps/api/tests/test_m06_reports_consistency.py`
- **Ref:** `d205a2e`

### 2026-10-18 06:17 UTC - Melorin M6 - ci-deploy, other, scripts  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** ci(M6.11): wire guard scripts into quality gate, CI and Makefile; guard checks the wiring
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (4):** `.github/workflows/ci.yml`, `Makefile`, `scripts/check_quality_config.py`, `scripts/run_quality_gate.sh`
- **Ref:** `9535eb7`

### 2026-10-18 06:17 UTC - Melorin M6 - api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** test(M6.10): use >=32-byte JWT key in tests and fail on InsecureKeyLengthWarning
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (2):** `apps/api/pyproject.toml`, `apps/api/tests/conftest.py`
- **Ref:** `a33850a`

### 2026-10-18 06:15 UTC - Melorin M6 - tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** test(M6.7): formatter-stable source-contract tests via read_source/normalize_source
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (60):** `apps/api/tests/_source.py`, `apps/api/tests/test_admin_safe_delete.py`, `apps/api/tests/test_admin_sections_contract.py`, `apps/api/tests/test_bot_store_binding.py`, `apps/api/tests/test_core_allocation_contract.py`, `apps/api/tests/test_core_allocation_db.py`, `apps/api/tests/test_f007_f010_hardening.py`, `apps/api/tests/test_f026_f032_hardening.py` (+52 more)
- **Ref:** `776cba3`

### 2026-10-18 06:10 UTC - Melorin M6 - tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** fix(M6.6): make unit tests hermetic against ambient MELORIN_* env and .env
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `apps/api/tests/conftest.py`
- **Ref:** `67637a7`


### 2026-10-18 05:17 UTC - Claude (M report) - api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** style(M): apply ruff format (mechanical, no behaviour change) - Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com> Claude-Session: https://claude.ai/code/session_011qiu7fzG4c5KLG6BK9aEBh
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (136):** `apps/api/melorin/app.py`, `apps/api/melorin/channels/telegram.py`, `apps/api/melorin/cli.py`, `apps/api/melorin/core/codes.py`, `apps/api/melorin/core/config.py`, `apps/api/melorin/core/crypto.py`, `apps/api/melorin/core/db.py`, `apps/api/melorin/core/deps.py` (+128 more)
- **Ref:** `d7bd299`

### 2026-10-18 05:17 UTC - Claude (M report) - ci-deploy, admin-web, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** fix(M): UTC day bucketing, CI bootstrap/e2e credentials, stale quality checks, web tooling - - admin timeseries: force UTC day on PostgreSQL (date(timestamptz) used DB session tz and dropped sales off the UTC axis) - CI/e2e: bootstrap needs a 24+ char password and a TOTP secret; e2e_smoke now sends…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (12):** `.github/workflows/ci.yml`, `apps/admin-web/package-lock.json`, `apps/admin-web/package.json`, `apps/api/melorin/modules/admin/timeseries.py`, `apps/api/tests/test_l04_l05_quality_migration.py`, `apps/api/tests/test_m01_admin_timeseries.py`, `apps/store-web/package-lock.json`, `apps/store-web/package.json` (+4 more)
- **Ref:** `28eedae`


### 2026-10-18 UTC - Claude - reseller bot, admin-web, api
- **Before:** the reseller Telegram bot was never connected. `telegram_reseller` was off by default (compose profile) and could only
  start from `MELORIN_TELEGRAM_RESELLER_TOKEN`/`MELORIN_RESELLER_BOTS_JSON`; the bot token of an approved reseller was stored encrypted in
  `stores.bot_token_enc` but nothing ever read it. Admin could list stores (read-only) but not edit a reseller.
- **Problem:** approving a reseller created a store + bot binding with no running bot; no way to see whether a bot works; no admin editing of
  name/domain/limits/token; tokens could leak into logs through httpx error text.
- **Action:** Core is now the source of truth. `modules/reseller/bots.py` (+ migration 0025: `stores.bot_enabled/bot_status/bot_status_detail/bot_seen_at`)
  serves `GET /internal/reseller-bots` and receives `POST /internal/reseller-bots/{id}/status` (private network only; blocked in Caddy/nginx and
  refused when forwarding headers are present). `telegram-reseller/runner.py` is a supervisor: one isolated runner per store, restart on token change,
  stop on suspend/disable, health reported back, 401 = revoked (no retry loop), token redaction in logs, heartbeat healthcheck; compose now always runs it.
  Reseller bot UX: store welcome/support/rules texts, owner-only `🏪 مدیریت فروشگاه` (/manage) with debt state and pending receipts, no "become a reseller".
  Admin: `modules/admin/resellers.py` (`GET/PATCH /admin/resellers`, `PUT/DELETE /admin/resellers/{id}/bot-token`, `POST .../verify-bot`) and the
  "نمایندگان" screen (live bot state, edit identity/status/debt limit/switches/token/texts). Everything audited; token is write-only.
- **After:** `pytest` 528 → 560 passed (+32 new in `test_s01_*`); `vite build` OK; migration chain 0024 → 0025.
- **Ref:** patch `melorin-reseller-bot.patch` on top of 49218ac.

### 2026-10-17 22:16 UTC - Claude - admin-web, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(admin): rename cooperation price to reseller price; read-only view of reseller retail prices
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (3):** `apps/admin-web/src/BundlesView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/api/melorin/modules/admin/router.py`
- **Ref:** `fd60701`

### 2026-10-17 22:03 UTC - Claude - admin-web, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(admin,core): simplify products/bundles screens; per-package reseller switch; every package in every bundle - - products: no reseller price field; main price only; main/reseller switches (main off => resellers off) - bundles: packages list with per-bundle store price, cooperation price (only wh…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (9):** `apps/admin-web/src/BundlesView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/api/alembic/versions/0024_product_reseller_switch.py`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/admin/schemas.py`, `apps/api/melorin/modules/catalog/models.py`, `apps/api/melorin/modules/catalog/service.py`, `apps/api/melorin/modules/vpn/allocation.py` (+1 more)
- **Ref:** `359fe88`


### 2026-10-17 20:14 UTC - Claude - api, tests, store-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(core,bots,store-web): automatic sign-in from the bot account button - - Core: POST /me/web-handoff builds the store-site URL with a single-use 2-minute token; POST /auth/web-handoff/redeem exchanges it for a session - Bots only ask Core for the URL; site signs the user in automatically and off…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (6):** `apps/api/melorin/modules/identity/router.py`, `apps/api/melorin/modules/identity/schemas.py`, `apps/api/melorin/modules/identity/service.py`, `apps/api/tests/test_web_handoff.py`, `apps/store-web/src/App.jsx`, `apps/telegram-main/runner.py`
- **Ref:** `e9dd979`

### 2026-10-17 20:06 UTC - Claude - api, tests, store-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(bots,store-web): account button opens the store website, link Google to account - - Main and reseller bots: "حساب کاربری" renamed to "حساب من در سایت"; opens the store site via a URL button - API: expose store domain; POST /me/identities/google links a Google account to the signed-in user - st…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (9):** `apps/api/melorin/modules/catalog/router.py`, `apps/api/melorin/modules/catalog/schemas.py`, `apps/api/melorin/modules/identity/router.py`, `apps/api/melorin/modules/identity/schemas.py`, `apps/api/melorin/modules/identity/service.py`, `apps/api/tests/test_o01_google_signin.py`, `apps/store-web/src/App.jsx`, `apps/store-web/src/Dashboard.jsx` (+1 more)
- **Ref:** `59248d2`


### 2026-10-17 18:44 UTC - Claude - reseller-catalog  _(auto)_
- **Before:** reseller stores had no store_products / store_bundles rows, so their price table was empty and they could not sell
- **Problem:** nothing linked a reseller store to the main packages and reseller-enabled bundles
- **Action:** auto-link on reseller store creation and on package / bundle creation or enable; migration 0023 backfills existing stores; existing rows are never overwritten
- **After:** new tests pass, full suite 516 passed, migration verified on PostgreSQL (backfill, idempotent, existing rows untouched)
- **Files (5):** `apps/api/alembic/versions/0023_link_resellers_to_main_catalog.py`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/reseller/linking.py`, `apps/api/melorin/modules/reseller/provisioning.py`, `apps/api/tests/test_reseller_catalog_linking.py`
- **Ref:** `8a2def9`


### 2026-10-17 18:13 UTC - Claude - admin-web, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Rename panel groups to bundles: models, API routes, DB tables/columns (migration 0022), admin/store UI, bots, tests (step 3/3)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (38):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/BundlesView.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/ServerForm.jsx`, `apps/admin-web/src/infra.jsx`, `apps/api/alembic/versions/0022_panel_group_to_bundle.py` (+30 more)
- **Ref:** `f1a1264`


### 2026-10-17 18:09 UTC - Claude - other, admin-web, db  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Rename sales pool identifiers to bundle: API routes, schemas, DB tables (migration 0021), admin/store UI, bots, tests (step 2/3)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (32):** `README.md`, `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/infra.jsx`, `apps/admin-web/src/styles.css`, `apps/api/alembic/versions/0021_pool_to_bundle.py`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/admin/schemas.py`, `apps/api/melorin/modules/catalog/models.py` (+24 more)
- **Ref:** `044e678`


### 2026-10-17 18:05 UTC - Claude - other, admin-web, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Rename sales pool / panel group wording to sales bundle in comments, docstrings, README and docs (step 1/3)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (18):** `README.md`, `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/kit.jsx`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/catalog/models.py`, `apps/api/melorin/modules/catalog/router.py`, `apps/api/melorin/modules/reseller/router.py`, `apps/api/melorin/modules/reseller/schemas.py` (+10 more)
- **Ref:** `6390a52`


### 2026-10-17 13:30 UTC - Claude - api, store-web, tests, docs
- **Before:** a reseller had ONE retail price per package for the whole store (`store_products.customer_price`); the web reseller panel had no place to set prices at all (only the Telegram bot did), and a package sold in a cheap and a dear pool could not be priced differently.
- **Problem:** the reseller panel could not price the packages of each sales pool (بسته فروش) in the reseller's own store.
- **Action:** new table `store_pool_prices` (migration `0020_store_pool_prices`) = the reseller's price of one package in ONE pool; it wins over the store-wide price, which stays as the fallback. `vpn/allocation.py` resolves the charged price in one place (`retail_price`) for listing, quote and checkout, and refuses a pool price below THAT pool's reseller price (`set_pool_price`, `set_prices_batch`, all-or-nothing). New endpoints `PUT /stores/{id}/reseller/pools/{pool_id}/prices/{product_id}` and `POST /stores/{id}/reseller/prices/batch`; `GET …/reseller/prices` gains `pools[]`. Admin: exact "stores below cost" warning per pool; removing a package/pool/product also removes the resellers' prices for it. store-web: new "قیمت‌گذاری" tab (`ResellerPricing.jsx`): scope chips (base price + one per pool), cost → price → profit → state rows, quick tools (markup, copy from another pool) that only fill a draft, one "save all" request, unsaved-changes guard.
- **Reseller Telegram bot:** `/prices` now prices a package per sales pool exactly like the web panel (pool buttons + "قیمت کلی فروشگاه"), through the same core endpoints (`PUT …/reseller/pools/{pool_id}/prices/{product_id}` and `PUT …/reseller/prices/{product_id}`); the bot holds no price rule, the core validates the cost floor and resolves the charged price.
- **After:** `pytest` 507 passed (new `test_reseller_pool_prices.py`, 16 tests incl. migration up/down); `vite build` OK; jsdom check of the tab (scope switch, below-cost warning, markup, copy, batch payload, server-error mapping). Existing stores keep selling at the same prices (no row = store-wide price). The Telegram reseller bot still sets the store-wide price.
- **Files:** `apps/api/melorin/modules/{catalog/{models,service,router},vpn/allocation,reseller/{router,schemas},orders/service,admin/router}.py`, `apps/api/alembic/versions/0020_store_pool_prices.py`, `apps/store-web/src/{ResellerPricing,Reseller}.jsx`, `apps/api/tests/{test_reseller_pool_prices,test_admin_safe_delete}.py`, `docs/API-ROUTES-ACTIVE.md`

### 2026-10-17 12:21 UTC - Claude - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Telegram login: main bot @username box in admin settings (auto-detect via getMe or manual) (telegram-main-bot-username.patch)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (4):** `apps/admin-web/src/TelegramLoginSettings.jsx`, `apps/api/melorin/modules/admin/integrations.py`, `apps/api/tests/test_r01_telegram_login_settings.py`, `docs/TELEGRAM-WEB-LOGIN.md`
- **Ref:** `690d3f9`


### 2026-10-17 12:00 UTC - Claude - auth, store-web, admin-web, infra
- **Before:** admin-web used a hand-made "Google" button driving One Tap (`prompt()`); store-web used `renderButton` but `initialize()` ran twice; ID tokens were checked through the debugging-only `/tokeninfo` endpoint with no nonce, so a leaked token could be replayed; no explicit `exp`/`iat` requirement; admin login page showed API errors as a generic message (it read `payload.code` instead of `payload.error.code`).
- **Problem:** the sign-in did not follow Google's official "Sign in with Google" guidance (button, theme, initialisation, token verification, COOP).
- **Action:** both apps now share one `GoogleSignIn.jsx` using Google's official button (theme-aware outline/filled_black, 200-400px, `locale: fa`, loading skeleton, retry, `disableAutoSelect` on sign-out), a single `initialize()` with a server nonce; new `GET /auth/google/nonce` (httpOnly cookie) enforced by `POST /auth/google`; tokens verified locally against Google's JWKS (RS256, iss, aud, exp, nonce; cached, survives a Google outage); admin Google button unlocks after the TOTP code is typed; Caddy sends `Cross-Origin-Opener-Policy: same-origin-allow-popups`; connectivity test and docs use `www.googleapis.com/oauth2/v3/certs`.
- **After:** `pytest` 446+ passed (new `test_r01_google_token_verification.py`), `vite build` OK for both apps, jsdom check: one `initialize()` per page load, theme switch re-renders without re-initialising.
- **Files:** `apps/api/melorin/modules/identity/{service,router}.py`, `apps/api/melorin/modules/admin/integrations.py`, `apps/{store,admin}-web/src/{GoogleSignIn,App,AdminAuth}.jsx`, `infra/Caddyfile`, `docs/GOOGLE-LOGIN-SETUP-{EN,FA}.md`, tests.

### 2026-10-17 09:08 UTC - Claude - tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** test: align Google sign-in static check with store-web renderButton
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `apps/api/tests/test_o01_google_signin.py`
- **Ref:** `deb57b0`

### 2026-10-17 09:08 UTC - Claude - store-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** store-web: use Google renderButton so Google errors are visible (google-renderbutton.patch)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `apps/store-web/src/GoogleSignIn.jsx`
- **Ref:** `11a1e9e`


### 2026-10-16 11:03 UTC - archerhabibi - config, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Add website login approved in the Telegram bot - Device-authorization style flow with browser binding (poll token), number matching, device/IP context in the bot and a "not me" button. Adds migration 0019_telegram_web_login, Core endpoints, bot runner handlers, store-web TelegramLogin dialog, GC wo…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (18):** `.env.example`, `apps/api/alembic/versions/0019_telegram_web_login.py`, `apps/api/melorin/app.py`, `apps/api/melorin/core/config.py`, `apps/api/melorin/modules/identity/models.py`, `apps/api/melorin/modules/identity/schemas.py`, `apps/api/melorin/modules/identity/telegram_web.py`, `apps/api/melorin/modules/identity/telegram_web_router.py` (+10 more)
- **Ref:** `e499eda`


### 2026-10-16 10:13 UTC - Claude - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Add Google Sign-In to store-web and admin-web - Applies melorin-google-signin.patch, plus fixes found in review: - /auth/google: enforce admin TOTP (no 2FA bypass), set refresh cookie, honour registration flag + referral signup - Caddy CSP allows Google Identity Services; VITE_GOOGLE_CLIENT_ID pass…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (14):** `apps/admin-web/.env.example`, `apps/admin-web/Dockerfile`, `apps/admin-web/src/AdminAuth.jsx`, `apps/admin-web/src/GoogleSignIn.jsx`, `apps/api/melorin/modules/identity/router.py`, `apps/api/melorin/modules/identity/schemas.py`, `apps/api/melorin/modules/identity/service.py`, `apps/api/tests/test_o01_google_signin.py` (+6 more)
- **Ref:** `0e07401`


### 2026-10-16 08:02 UTC - x - other  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** the first admin e-mail defaulted to admin@<store domain> without asking.
- **Action:** melorin.sh install now prompts for and validates the admin e-mail; READMEs updated.
- **After:** install asks store domain, admin domain, admin e-mail, bot token.
- **Files (3):** `README.fa.md`, `README.md`, `melorin.sh`
- **Ref:** `364e293`


### 2026-10-16 06:51 UTC - x - other, scripts  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** Install required several manual steps and env vars.
- **Action:** add get.sh one-liner and melorin.sh menu (install/update/env/panel/service/status/uninstall); installer remembers install mode; READMEs updated.
- **After:** bash <(curl -fsSL .../get.sh) installs with only store domain, admin domain and bot token.
- **Files (5):** `README.fa.md`, `README.md`, `get.sh`, `melorin.sh`, `scripts/install_server.sh`
- **Ref:** `c90c45b`


### 2026-10-16 04:47 UTC - Claude - infra, api, store-web
- **Before:** Caddy served only `MELORIN_DOMAIN` and `MELORIN_ADMIN_DOMAIN`. A reseller store created with its own domain got no certificate and no route, and the storefront always loaded the main store.
- **Problem:** The reseller domain was stored in Core but never reachable through Caddy.
- **Action:** Caddy on-demand TLS: global `on_demand_tls` with `ask http://api:8000/api/v1/tls/ask`, a catch-all `https://` site (storefront + `/api`, same blocked ops, no admin) and an `http://` to HTTPS redirect. New public endpoint `GET /api/v1/tls/ask?domain=` (200 only for an active reseller `Store.domain`). Store web resolves the store from `window.location.hostname` (`/stores/by-domain/<host>`) and falls back to the main store. Runbook and installer hints cover DNS and `EXTERNAL_PROXY=true`.
- **After:** `caddy validate` on the new Caddyfile: valid. API suite 380 passed, 1 skipped (3 new tests). `check_g001_g010.py` still reports G006 and G010 failed, same as before this change. Not run: a real certificate issuance, the frontend build.
- **Ref:** (commit of this patch)


### 2026-10-16 04:05 UTC - Claude - telegram-main, api, admin-web, store-web, db
- **Before:** `/reseller` in the main bot only opened a support ticket. A real reseller application (web form) needed the store domain and the bot token up front, and an application without them could only be rejected.
- **Problem:** Resellers could not apply from Telegram. Owner decision: the bot sends the request first and collects the domain and bot token only after the request is approved (giving the token in Telegram is acceptable).
- **Action:** Two-step application. `POST /reseller/applications` accepts no domain/token (both or neither); admin approval of such a request sets status `awaiting_details` (new column `approved_debt_limit`, migration 0018) and notifies the applicant; new `POST /reseller/applications/{id}/details` validates domain + token (format, uniqueness, Telegram getMe, 424 when Telegram is unreachable) and creates the store via the shared `reseller/provisioning.py`. Main bot: `/reseller` asks name + description, later domain + token, deletes the token message, never echoes/logs/stores the token; `/cancel` added; reseller bots keep the ticket behaviour. Admin web: new status filter, approve-as-request, withdraw approval. Store web: details form for `awaiting_details`. Web one-step form and old applications unchanged.
- **After:** Full API suite 377 passed, 1 skipped (new: 7 API tests, 9 Telegram flow tests; one old test updated because a request without domain/bot is now approvable instead of `APPLICATION_INCOMPLETE`). Not run: real Telegram sandbox, PostgreSQL migration, frontend build.
- **Ref:** (commit of this patch)


### 2026-10-16 03:19 UTC - Claude - admin-web, api, store-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** fix: include modified files of melorin-reseller-applications.patch (models, routers, schemas, admin/store UI, cli)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (9):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/api/melorin/cli.py`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/catalog/router.py`, `apps/api/melorin/modules/reseller/router.py`, `apps/api/melorin/modules/reseller/schemas.py`, `apps/api/melorin/modules/stores/models.py` (+1 more)
- **Ref:** `3883ff2`


### 2026-10-16 03:19 UTC - Claude - admin-web, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(reseller): applications carry store domain + reseller bot token (melorin-reseller-applications.patch)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (4):** `apps/admin-web/src/ResellerApplicationsView.jsx`, `apps/api/alembic/versions/0017_reseller_domain_bot.py`, `apps/api/melorin/modules/reseller/identity.py`, `apps/api/tests/test_o01_reseller_applications.py`
- **Ref:** `49b5970`


### 2026-10-16 01:21 UTC - Claude - docs  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** README did not describe apps/admin-web, store-web or the telegram apps, nor the redesigned infra screens.
- **Action:** added the apps to Layout and a short Admin panel section.
- **After:** README renders the new section; admin-web build verified (vite build OK).
- **Files (1):** `README.md`
- **Ref:** `b842e73`

### 2026-10-16 01:19 UTC - Claude - admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(admin-web): infra UI redesign — KPI bar, rings/segmented meters, sort + view toggle, pool flow cards (melorin-admin-ui-redesign.patch)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (6):** `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/infra.jsx`, `apps/admin-web/src/kit.jsx`, `apps/admin-web/src/styles.css`
- **Ref:** `f3362a4`


### 2026-10-16 00:58 UTC - archerhabibi - admin-web, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat: sales pools v5 — pool-based selling, per-pool package prices, connection kind, panel labels, reseller bot prices (sales-pools-v5.patch)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (34):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/InfraHealthView.jsx`, `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/ServerForm.jsx`, `apps/admin-web/src/infra.jsx` (+26 more)
- **Ref:** `31e0e63`


### 2026-10-16 00:02 UTC - archerhabibi - admin-web, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Revert "Merge apply/sales-pools-v2: sales pools (pool-based selling, per-pool package prices, connection kind, customer panel labels)" - This reverts commit 9d3ebf472b9c52bef4f2f9dff74f11c1571cbf07, reversing changes made to 47749ee585f1f89752f8b25270921c7f28a42968.
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (30):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/InfraHealthView.jsx`, `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/ServerForm.jsx`, `apps/admin-web/src/infra.jsx` (+22 more)
- **Ref:** `e0fa6c2`


### 2026-10-15 23:35 UTC - archerhabibi - admin-web, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat: sales pools v2 — pool-based selling with per-pool package prices, connection kind, customer-facing panel labels (sales-pools-v2.patch)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (30):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/InfraHealthView.jsx`, `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/ServerForm.jsx`, `apps/admin-web/src/infra.jsx` (+22 more)
- **Ref:** `280309f`


### 2026-10-15 06:54 UTC - Claude - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(admin): safe delete for products/panels/servers/panel groups — 409 when history exists (melorin-admin-safe-delete.patch)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (9):** `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/ServerForm.jsx`, `apps/admin-web/src/kit.jsx`, `apps/admin-web/src/ui.jsx`, `apps/api/melorin/modules/admin/router.py`, `apps/api/tests/test_admin_safe_delete.py` (+1 more)
- **Ref:** `d156e5c`


### 2026-10-15 05:30 UTC - Claude - admin-web
- **Before:** ساخت یک محصول قابل فروش یعنی گذر از ۴ صفحه (پنل، سرور، بسته، محصول) با تنظیمات تکراری؛ صفحه‌ی «سرورها» فقط فرزند پنل بود، «محصولات مجاز» روی سرور با مسیر محصول←بسته←پنل تکراری بود، تغییر بسته از فرم پنل به‌خاطر کلید اشتباه (`panels` به‌جای `panel_ids`) اصلاً ذخیره نمی‌شد، صفحه‌ی بسته آمار سرور نداشت (فقط panels/groups بارگذاری می‌شد) و صفحه‌ی سلامت همه‌ی محصولات را «بدون سرور» نشان می‌داد.
- **Problem:** طراحی گنگ و چندمرحله‌ای؛ یک رابطه در دو جا با رفتار متفاوت؛ باگ‌های بالا.
- **Action:** ادغام «سرورها» در «پنل‌ها و سرورها» (ساخت پنل + اولین سرور + عضویت بسته در یک فرم، ورود CSV به‌ازای پنل، ریدایرکت `#/servers`)؛ «محصولات مجاز» سرور به بخش پیشرفته رفت؛ بسته: انتخاب دستی/نام‌گذاری/نمایندگان پیشرفته، افزودن/برداشتن محصول از خود بسته؛ محصول: ساخت بسته سریع، کد خودکار، جزئیات و انتشار فروشگاه‌ها جمع‌شونده؛ راهنمای «قدم بعدی» بالای هر سه صفحه؛ اصلاح صفحه‌ی سلامت. بدون تغییر در API/DB.
- **After:** `vite build` سبز، `pytest` قراردادهای UI (۲۲ تست) سبز، تست مرورگر با API ساختگی بدون خطای کنسول.
- **Ref:** docs/INFRA_REDESIGN_FA.md

### 2026-10-14 22:50 UTC - Claude - api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(api): GET /admin/products/{id}/availability so the admin form loads stored store state - Matches the request merge4pages.patch's ProductsView already sends; previously only POST existed.
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (2):** `apps/api/melorin/modules/admin/router.py`, `apps/api/tests/test_m08_catalog_admin_edit_contract.py`
- **Ref:** `8c500e7`

### 2026-10-14 22:43 UTC - Claude - admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** fix(admin-web): ProductsView — restore declarations swallowed by trailing // comments - 'const { call, idx } = infra' and the filter/layout/drawer/busy useState line were accidentally inside line comments (since 9677157), so 'call', 'idx', 'filter', 'layout', 'drawer', 'busy' were undefined at runt…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `apps/admin-web/src/ProductsView.jsx`
- **Ref:** `c3aba54`

### 2026-10-14 22:43 UTC - Claude - admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(admin-web): merge panels+servers view, shared capTone/ChipList helpers, store-availability load (merge4pages.patch) - Applied merge4pages.patch on current main. Manual conflict resolution: - PanelGroupsView/ServersView: import lines rebased onto the Paginator/RefreshCw imports added in 3dba98c…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (6):** `apps/admin-web/src/App.jsx`, `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/ServersView.jsx`, `apps/admin-web/src/kit.jsx`
- **Ref:** `bef9266`


### 2026-10-14 22:13 UTC - Claude - admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** fix(admin-web): add missing RefreshCw/Paginator imports and reuse shared num helper in Paginator
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (3):** `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/ServersView.jsx`, `apps/admin-web/src/kit.jsx`
- **Ref:** `3dba98c`


### 2026-10-14 17:38 UTC - archerhabibi - admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** fix(admin-web): move infra-health into the Infrastructure nav group items - The entry sat outside the group's items array, so it was not a valid nav item. Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `apps/admin-web/src/App.jsx`
- **Ref:** `9b613e7`


### 2026-10-14 16:59 UTC - archerhabibi - admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(admin-web): apply melorin-combined patch (admin refactor + remaining bugs + advanced features) - Applied on top of 1cbcabd. Fixes needed for the patch to build: - PanelsView: invalid \" escape inside JSX attribute string (hint now a JS expression) - InfraHealthView: toast comes from props (not…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (9):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/InfraHealthView.jsx`, `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/ServersView.jsx`, `apps/admin-web/src/infra.jsx` (+1 more)
- **Ref:** `9677157`


### 2026-10-14 15:33 UTC - hassanhabibi - admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** fix(admin-web): apply remaining patch (#6, #8, #9, #11, #12) - - #6 PanelsView: expose the Mock panel kind only in dev builds - #8 infra: reload() reads loaders through a ref, no stale closure - #9 ServersView: default layout is "grid" - #11 PanelGroupsView: skeleton waits only for group rows - #12…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (5):** `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/ServersView.jsx`, `apps/admin-web/src/infra.jsx`
- **Ref:** `67d611a`


### 2026-10-14 14:06 UTC - Claude - apps/admin-web PanelsView  _(auto)_
- **Before:** PanelsView re-defined num/tint/errText/Dot/Stat/Field/Segmented/Toggle/Switch locally; save did infra.reload() then check() (stale health flash, panels.load() twice); validation errors passed as gray hint=; thead built with index keys.
- **Problem:** fixes in kit.jsx/infra.jsx were invisible in PanelsView; race on health status after save.
- **Action:** import shared helpers (kit.jsx/infra.jsx); PanelSwitch wraps kit Switch (label + title, additive title prop in kit Switch); save runs health probe first then a single reload, keeping the "failed" vs "unhealthy" toast; validation strings use Field error=; static thead; useAlive(); Dot keeps ping; fi…
- **After:** vite build OK, scripts/check_frontend_contracts.py passes (9).
- **Files (2):** `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/kit.jsx`
- **Ref:** `6d4888b`


### 2026-10-14 06:03 UTC - archerhabibi - admin-web, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(admin): infrastructure redesign — panel → server → group → product chain - - Servers become their own page (#/servers) instead of a tab inside Panels - New shared infra.jsx: useInfra data model, InfraChain header, Rel/RelChip links, serverState/reach helpers mirroring the allocation core - Pan…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (9):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/ServerForm.jsx`, `apps/admin-web/src/ServersView.jsx`, `apps/admin-web/src/infra.jsx` (+1 more)
- **Ref:** `1cbcabd`


### 2026-10-14 00:36 UTC - Claude - api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** fix(tickets): reject whitespace-only admin replies and edits
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (2):** `apps/api/melorin/modules/admin/router.py`, `apps/api/tests/test_n01_ticket_desk.py`
- **Ref:** `ad2a05b`


### 2026-10-14 00:14 UTC - Claude - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(admin): redesign panels & servers (servers tab, PATCH/state/list endpoints, tests)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (7):** `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ServerForm.jsx`, `apps/admin-web/src/ServersView.jsx`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/admin/schemas.py`, `apps/api/tests/test_server_admin_management.py`, `apps/api/tests/test_server_admin_ui_contract.py`
- **Ref:** `799d551`


### 2026-10-13 23:46 UTC - archerhabibi - tests, bot  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(telegram-main): redesigned bot UX (in-place screens, quote card, account cards, renewal) - - Inline navigation edits the tapped message in place (screen()), with a fallback to a new message when Telegram refuses the edit; "not modified" is ignored. - Quote card shows price, discount, wallet ba…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (4):** `apps/api/tests/test_telegram_ux_v2.py`, `apps/telegram-main/requirements.txt`, `apps/telegram-main/runner.py`, `apps/telegram-reseller/requirements.txt`
- **Ref:** `c6d7a9f`


### 2026-10-13 23:36 UTC - archerhabibi - api, tests, bot  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(delivery): single Telegram post with QR, subscription link and wallet balance - - New order.delivery outbox topic handled by modules/orders/delivery.py: one photo message (QR of the subscription link) whose caption carries account details, tap-to-copy link and the wallet balance right after th…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (9):** `apps/api/melorin/channels/telegram.py`, `apps/api/melorin/core/events.py`, `apps/api/melorin/modules/orders/delivery.py`, `apps/api/melorin/modules/vpn/service.py`, `apps/api/melorin/worker/runner.py`, `apps/api/pyproject.toml`, `apps/api/requirements.txt`, `apps/api/tests/test_order_delivery_post.py` (+1 more)
- **Ref:** `dcb45a9`


### 2026-10-13 23:16 UTC - archerhabibi - api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(worker): Telegram alert to admins when provisioning fails - - PROVISIONING_FAILED now sends a Telegram message to every active super admin (via the main bot) with order number, error and refund outcome. The previous _notify call had no user_id and was a silent no-op. - Per-admin dedup keys: ou…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (4):** `apps/api/melorin/modules/orders/service.py`, `apps/api/melorin/modules/vpn/service.py`, `apps/api/melorin/worker/runner.py`, `apps/api/tests/test_provisioning_failed_telegram.py`
- **Ref:** `7db5455`


### 2026-10-14 UTC - claude - tickets (api, admin-web, store-web, telegram, db)
- **Before:** Admin ticket screen was a plain table with a one-line reply box; customers could not edit anything; staff replies never reached the customer (the `ticket.updated` outbox event only logged); no priority, no internal notes.
- **Problem:** Support workflow was slow and one-way: no inbox view, no way to fix a typo in a message or rename a ticket, no triage by priority, and customers were not told when support answered.
- **Action:** Migration 0015 (`tickets.priority`, `ticket_messages.is_internal`, `ticket_messages.edited_at`). New `tickets/service.py`; customer API gained `GET|PATCH /tickets/{id}` and `PATCH /tickets/{id}/messages/{mid}`; admin API gained filtered list with customer/preview data, detail, `PATCH`, reply/internal note and message edit (all audited). Staff replies now enqueue a `notification.send` (Telegram + in-app). New admin `TicketsView.jsx` (inbox + conversation, quick replies, internal notes, inline edit, polling). Store-web ticket screen redesigned as a chat with edit/close/re-open. Telegram bot: guided new-ticket flow, ticket view with edit-my-message / rename / close / re-open. Tests: `tests/test_n01_ticket_desk.py`.
- **After:** `pytest` 292 passed, 1 skipped (baseline 278 + 14 new); admin-web and store-web `vite build` OK; jsdom flow test of the admin desk passed.
- **Ref:** _pending commit_


### 2026-10-13 23:05 UTC - archerhabibi - db, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** feat(api): 6-char short codes, 4-attempt provisioning retry and auto-refund - - Add core/codes.py: 4-char sequence prefix + 2-char random suffix codes (32-symbol unambiguous alphabet) for orders and tickets. - Migration 0014: order/ticket sequences, orders.number VARCHAR(6) with backfill, tickets.n…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (11):** `apps/api/alembic/versions/0014_short_codes_and_auto_refund.py`, `apps/api/melorin/core/codes.py`, `apps/api/melorin/core/settings_store.py`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/orders/models.py`, `apps/api/melorin/modules/orders/service.py`, `apps/api/melorin/modules/tickets/models.py`, `apps/api/melorin/modules/tickets/router.py` (+3 more)
- **Ref:** `db29ef1`


### 2026-10-13 20:22 UTC - archerhabibi - admin-web, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Core allocation: single place decides group/panel/server for every channel - - Product.default_panel_group_id (migration 0013) applied by the core to bot, site and tests - vpn/allocation.py: resolve_order_group (before payment) and resolve_allocation (provisioning) - Server product_codes validated …
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (11):** `apps/admin-web/src/ProductsView.jsx`, `apps/api/alembic/versions/0013_product_default_panel_group.py`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/admin/schemas.py`, `apps/api/melorin/modules/catalog/models.py`, `apps/api/melorin/modules/orders/service.py`, `apps/api/melorin/modules/vpn/allocation.py`, `apps/api/melorin/modules/vpn/service.py` (+3 more)
- **Ref:** `687fd05`


### 2026-10-13 14:40 UTC - archerhabibi - admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Admin: add server creation form to Panels view - New ServerForm component posts to /api/v1/admin/servers; opened from a new "افزودن سرور" button in PanelsView. Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com> Claude-Session: https://claude.ai/code/session_01VAXgCKFRzCWz5GfoX82fwQ
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (2):** `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/ServerForm.jsx`
- **Ref:** `548270d`


### 2026-10-13 06:23 UTC - archerhabibi - api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Worker: periodic jobs accept the ARQ ctx argument - ARQ passes ctx positionally to every cron job; the zero-argument job functions would raise TypeError. Add `ctx=None` to all periodic jobs and a contract test. Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com> Claude-Session: https://claude…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (2):** `apps/api/melorin/worker/jobs.py`, `apps/api/tests/test_worker_cron_ctx_contract.py`
- **Ref:** `86cc782`


### 2026-10-13 05:58 UTC - archerhabibi - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Wallet/payment fix v2: telegram top-up callback, payments page settings, job adapter close - - Telegram: wallet callback receives "amount:<n>|custom"; parse it correctly and validate the amount (previously int("amount:200000") failed) - Admin Payments page now hosts the card/Zarinpal settings forms…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (5):** `apps/admin-web/src/AdminExtra.jsx`, `apps/api/melorin/worker/jobs.py`, `apps/api/tests/test_wallet_payment_regressions.py`, `apps/store-web/src/Dashboard.jsx`, `apps/telegram-main/runner.py`
- **Ref:** `2f5a706`


### 2026-10-13 05:05 UTC - archerhabibi - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Payments: zarinpal as supported destination, payment settings forms in admin - - gateway_catalog: add zarinpal (IRT/IRR); service maps unsupported currency to PAYMENT_CURRENCY_UNSUPPORTED (400) instead of an unhandled ValueError - Admin Settings: first-class forms for main-store card info and Zarin…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (4):** `apps/admin-web/src/AdminExtra.jsx`, `apps/api/melorin/modules/payments/gateway_catalog.py`, `apps/api/melorin/modules/payments/service.py`, `apps/api/tests/test_wallet_payment_regressions.py`
- **Ref:** `23cfe49`


### 2026-10-13 04:23 UTC - archerhabibi - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Admin: redesign products and panel-group views; editable products/groups - - New ProductsView / PanelGroupsView / shared kit in admin-web - PATCH /products: explicit null clears max_devices/description/category; duplicate code guard (PRODUCT_CODE_EXISTS) - PATCH /panel-groups: explicit null sales_l…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (7):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/PanelGroupsView.jsx`, `apps/admin-web/src/ProductsView.jsx`, `apps/admin-web/src/kit.jsx`, `apps/api/melorin/modules/admin/router.py`, `apps/api/tests/test_m08_catalog_admin_edit_contract.py`
- **Ref:** `e131b11`


### 2026-10-13 03:55 UTC - archerhabibi - admin-web, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Rename sales baskets to panel groups everywhere (API, DB, frontend, CI, tests) - - Models/modules: SalesBasket -> PanelGroup, SalesBasketPanel -> PanelGroupMember, StoreSalesBasket -> StorePanelGroup; vpn/baskets.py -> vpn/panel_groups.py - API: /sales-baskets -> /panel-groups (admin, public catalo…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (20):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/api/alembic/versions/0012_baskets_to_panel_groups.py`, `apps/api/melorin/models.py`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/admin/schemas.py`, `apps/api/melorin/modules/catalog/router.py`, `apps/api/melorin/modules/orders/models.py` (+12 more)
- **Ref:** `68ee7ef`


### 2026-10-13 03:40 UTC - archerhabibi - config, other, admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Admin IP allowlist: configurable in admin panel, OFF by default, not asked at install - - Remove MELORIN_ADMIN_ALLOWED_IPS env/config requirement and installer prompt - Store allowlist in DB (integration.admin_access); Settings -> Integrations UI section - Refuse enabling with empty list or without…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (15):** `.env.example`, `README.fa.md`, `README.md`, `apps/admin-web/src/AdminExtra.jsx`, `apps/api/melorin/cli.py`, `apps/api/melorin/core/config.py`, `apps/api/melorin/core/deps.py`, `apps/api/melorin/core/integrations.py` (+7 more)
- **Ref:** `992a169`


### 2026-10-13 02:53 UTC - Claude - scripts  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** installer: pin REPO_REF to the m07 hardening commit (9d8d4e0)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `scripts/install_server.sh`
- **Ref:** `d7d3728`

### 2026-10-13 02:53 UTC - Claude - config, other, admin-web  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** m07: admin IP allowlist, security headers, bootstrap/TOTP hardening, main-store product publishing + backfill (0011), admin error boundary - Applied from melorin-m07-03-16 patch with fixes found during verification: - 0011 revision id shortened to <=32 chars (alembic_version.version_num is varchar(…
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (24):** `.env.example`, `README.fa.md`, `README.md`, `apps/admin-web/nginx.conf`, `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/main.jsx`, `apps/api/alembic/versions/0011_backfill_main_products.py`, `apps/api/melorin/cli.py` (+16 more)
- **Ref:** `9d8d4e0`


### 2026-10-13 02:06 UTC - Claude - admin-web, db, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Sales baskets: panel pools, naming policy, store overrides (migration 0010); admin label renamed to 'سبد فروش VPN'
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (14):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/api/alembic/versions/0010_sales_baskets.py`, `apps/api/melorin/models.py`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/admin/schemas.py`, `apps/api/melorin/modules/catalog/router.py`, `apps/api/melorin/modules/orders/models.py` (+6 more)
- **Ref:** `1275da1`


### 2026-10-13 00:07 UTC - Claude - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Admin: re-apply panels management view / live clock with corrected PanelsView (fix swallowed busy/bulk state)
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (8):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/styles.css`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/admin/schemas.py`, `apps/api/tests/test_panel_admin_management.py`, `apps/store-web/src/ui.jsx`
- **Ref:** `15fc23f`

### 2026-10-13 00:06 UTC - Claude - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Revert "Admin: panels management view (edit/enable/health error), VPN products move, live clock; store date+time format" - This reverts commit 58a41e6fded5d4c95635c2028ae2e909c22720ed.
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (8):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/styles.css`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/admin/schemas.py`, `apps/api/tests/test_panel_admin_management.py`, `apps/store-web/src/ui.jsx`
- **Ref:** `007a045`


### 2026-10-12 23:46 UTC - Claude - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Admin: panels management view (edit/enable/health error), VPN products move, live clock; store date+time format
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (8):** `apps/admin-web/src/AdminExtra.jsx`, `apps/admin-web/src/App.jsx`, `apps/admin-web/src/PanelsView.jsx`, `apps/admin-web/src/styles.css`, `apps/api/melorin/modules/admin/router.py`, `apps/api/melorin/modules/admin/schemas.py`, `apps/api/tests/test_panel_admin_management.py`, `apps/store-web/src/ui.jsx`
- **Ref:** `58a41e6`


### 2026-10-12 22:49 UTC - Claude - admin-web, api, tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Admin web redesign: Vazirmatn fonts, dashboard trend chart, /admin/reports/timeseries endpoint
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (21):** `apps/admin-web/index.html`, `apps/admin-web/public/fonts/OFL.txt`, `apps/admin-web/public/fonts/Vazirmatn-Bold.woff2`, `apps/admin-web/public/fonts/Vazirmatn-ExtraBold.woff2`, `apps/admin-web/public/fonts/Vazirmatn-Medium.woff2`, `apps/admin-web/public/fonts/Vazirmatn-Regular.woff2`, `apps/admin-web/src/AdminAuth.jsx`, `apps/admin-web/src/AdminExtra.jsx` (+13 more)
- **Ref:** `70fd30c`


### 2026-10-12 21:28 UTC - Claude - bot  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Telegram main bot: handle custom top-up amount input
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `apps/telegram-main/runner.py`
- **Ref:** `deb0c6e`

### 2026-10-12 21:28 UTC - Claude - tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** tests: align migration tests with frozen 0001 DDL snapshot
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (3):** `apps/api/tests/test_h002_migration_source.py`, `apps/api/tests/test_h013_baseline_contract.py`, `apps/api/tests/test_i14_i22_regressions.py`
- **Ref:** `d7a5292`

### 2026-10-12 21:28 UTC - Claude - admin-web, api  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Admin: change-password endpoint and settings UI
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (3):** `apps/admin-web/src/AdminExtra.jsx`, `apps/api/melorin/modules/identity/router.py`, `apps/api/melorin/modules/identity/schemas.py`
- **Ref:** `5b5825c`

### 2026-10-12 21:18 UTC - Claude - tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** tests: follow I40/I41 docs to docs/history
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `apps/api/tests/test_i14_i22_regressions.py`
- **Ref:** `7368860`

### 2026-10-12 21:17 UTC - Claude - tests  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** tests: follow I39 audit doc to docs/history
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `apps/api/tests/test_i14_i22_regressions.py`
- **Ref:** `e44c19e`

### 2026-10-12 21:17 UTC - Claude - other, db, docs  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Apply LA10-LA22: frozen 0001 DDL snapshot, installer pinning, docs moved to docs/history
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (35):** `README.md`, `apps/api/alembic/versions/0001_initial.py`, `docs/history/I34_EXTERNAL_INTEGRATIONS.md`, `docs/history/I35_TEST_MATRIX.md`, `docs/history/I36_OPERATIONS_CLI.md`, `docs/history/I37_PRIVACY_RETENTION.md`, `docs/history/I38_PGCLOCK_GATEWAYS_IRT.md`, `docs/history/I39_IRT_IRR_AUDIT.md` (+27 more)
- **Ref:** `e51d204`

### 2026-10-12 21:17 UTC - Claude - bot  _(auto)_
- **Before:** _not provided by the author_
- **Problem:** _not provided by the author_
- **Action:** Telegram main bot: Persian public reply-keyboard menu
- **After:** _not provided by the author_ (see CI/Actions result for this commit)
- **Files (1):** `apps/telegram-main/runner.py`
- **Ref:** `77744e7`


### 2026-10-12 - Claude (with owner) - server-side log and SSH deploy restored
- **Before:** after the reset to 27b7ee5 there was no server operations log and no automatic deployment.
- **Problem:** changes made directly on the server were invisible to git, and updating the server was manual.
- **Action:** restored `scripts/ops_watch.sh`, `scripts/ops_log.sh`, `scripts/install_ops_watch.sh` (cron, called by
  the installer) and `.github/workflows/deploy.yml`; README, README.fa.md, CONTRIBUTING.md updated.
- **After:** scripts syntax-checked and the watcher was tested earlier on a scratch copy (baseline, new commit,
  hand edit, `.env` change, no secret values written). Deploy workflow needs the DEPLOY_* secrets before its first
  run; cron and workflow NOT yet run on the real server.
- **Ref:** this commit; details in `docs/REVIEW_CHANGES_2026-10-12.md`

### 2026-10-11 - Claude (with owner) - reset to 27b7ee5 and re-applied the agreed changes
- **Before:** `main` carried extra commits (custom ports, TLS-from-files, SMTP/backup installer, server-side logging).
- **Problem:** owner asked to return to commit 27b7ee5 and redo only: main-bot token at install, automatic change
  log, README with install steps, and the optional SMTP/S3 patch refreshed for 27b7ee5.
- **Action:** history reset to 27b7ee5; then added (1) `docs`/Admin-panel optional SMTP and S3 backup patch
  (`optional-smtp-s3`, installer hunk removed because 27b7ee5 had no installer), (2) `scripts/install_server.sh`
  asking for the main bot token, local age-encrypted backups, reseller bot behind compose profile `reseller`,
  (3) automatic change log (`changelog.yml`, `changelog_auto.py`, `.gitmessage`, `make setup-git`),
  (4) README install guide, `README.fa.md`, `CONTRIBUTING.md`, PR template.
- **After:** patch applies cleanly on 27b7ee5; test suite: 122 passed / 6 failed - the same 6 fail on plain
  27b7ee5 (not caused by the patch); the 7 new tests pass. Installer dry-run (stub docker): token prompt, invalid
  token handling and idempotent re-run OK. Real-server install and the GitHub workflows not yet run.
- **Ref:** this commit; details in `docs/REVIEW_CHANGES_2026-10-12.md`

### 2026-10-12 - Claude (with owner) - comprehensive review changes applied (melorin-complete-changes.patch)
- **Before:** `main` at 3b2262a (admin login by e-mail code, no referral first-reward guard, installer/compose without the review fixes).
- **Problem:** the comprehensive project review found issues across auth, referral, rate limiting/Redis, VPN adapter registry, worker, Dockerfile, compose and the installer.
- **Action:** applied the review patch (33 files): admin login via password + TOTP, migration `0009_referral_first_reward_guard`, changes in app/cli/config/ratelimit/redis, admin/identity/orders/referral/reseller/vpn modules, arq worker, Dockerfile, `docker-compose.yml` + new `docker-compose.external.yml`, `infra/alerts.yml`, `install_server.sh`, `run_quality_gate.sh`, store-web/admin-web auth, and tests.
- **After:** tree is byte-identical to the review zip; Python compile and shell syntax checks pass. Full test suite, migration on a real DB and the web builds NOT yet run.
- **Ref:** this commit; details in `docs/REVIEW_CHANGES_2026-10-12.md`

### 2026-10-12 - Claude (with owner) - L01-L22 patch applied (melorin-L01-L22.patch)
- **Before:** `main` at 3ffadfb; 21 tests failing (L-series contracts and stale review assertions), off-site backup mandatory in production, historical `I*.md` notes in the repo root.
- **Problem:** the L01-L22 review items were open: off-site backup was a hard requirement, Telegram healthchecks only checked that a token was set, the release matrix and migration smoke still targeted 0008, and the lint policy and docs layout did not match the gates.
- **Action:** applied the patch (65 files): off-site S3 backup optional again (local age-encrypted backup stays required); `scripts/telegram_healthcheck.py` (getMe) copied into both bot images; `migration_smoke.sh` checks 0009 and runs in CI; deterministic tie-break in migration 0009 dedup (`created_at`, then `id`); lint policy `E4/E9/F`; installer builds `.env.tmp`; `I17-I33` notes moved to `docs/history/`; `auth_cookie_smoke.py`; runbook and README additions. On top of the patch: the installer now promotes `.env.tmp` to `.env` after validation (the patch built it but never renamed it), and 7 stale or wrong test assertions were corrected (readiness ping, `.is_private`, fail-closed rate limit fixture, J04 fixture tokens, by-slug check pointed at the reseller runner, `parsed_api` name, J19 lint policy).
- **After:** `pytest` 157 passed, 1 skipped; `ruff check` clean; shell syntax and release matrix checks pass. NOT run: `ruff format --check` (fails on 80 files, pre-existing), PostgreSQL migration smoke, web builds, `npm audit`.
- **Ref:** this commit

### 2026-10-13 - Claude (with owner) - store-web redesign (melorin-store-redesign-patch)
- **Before:** `apps/store-web` used hard-coded colors, system font (Tahoma), a single light theme and inline styles.
- **Problem:** the storefront looked dated and had no shared design system, loading/error states or mobile navigation.
- **Action:** new design system (light/dark tokens in `styles.css`, Tailwind token mapping, shared primitives in `src/ui.jsx`); redesigned home, login/code/checkout dialogs, dashboard and reseller panel; self-hosted Vazirmatn via `@fontsource-variable/vazirmatn`. API calls and state logic unchanged.
- **After:** `npm run build` passes; `check_frontend_contracts.py` and `check_web_lockfiles.py` pass; visually checked on desktop/mobile in light and dark with a mocked API. Not run against a live Core.
- **Ref:** this commit

### 2026-10-17 - Claude (with owner) - Google login settings in the admin panel (melorin-google-login-settings.patch)
- **Before:** Google sign-in needed `MELORIN_GOOGLE_CLIENT_ID` in `.env` plus a rebuild of both web images (`VITE_GOOGLE_CLIENT_ID`).
- **Problem:** no way to configure, test or switch off Google login from the admin panel; no setup guidance.
- **Action:** new `integration.google_login` setting (Client ID + admin/store switches, no secret); `GET/PUT /admin/integrations/google`, `POST /admin/integrations/google/test`, public `GET /auth/google/config`; `/auth/google` reads the saved config and enforces the per-surface switches; new admin Settings card with origin copy-boxes and a step-by-step guide; admin-web and store-web read the config at runtime (env value stays as fallback); docs `GOOGLE-LOGIN-SETUP-FA/EN.md`; tests `test_q01_google_settings.py`, `test_o01_google_signin.py` updated.
- **After:** full API suite 425 passed, 1 skipped, 2 failed (`test_admin_safe_delete`, `test_integration_health` fail identically on the untouched tree); `ruff check` clean on the changed files (2 pre-existing F841 in other tests); admin-web and store-web `vite build` pass; `check_frontend_contracts.py` passes. NOT run: real Google login against a live Client ID, PostgreSQL, Docker build.
- **Ref:** this commit

### 2026-10-17 - Claude (with owner) - Telegram login settings in the admin panel (melorin-telegram-login-settings.patch)
- **Before:** website login with Telegram had one method (approve in the bot) whose lifetime/number matching came only from `.env`, with no admin UI; Telegram's OpenID Connect login was not supported.
- **Problem:** no way to switch Telegram login on/off, tune or test it from the panel, and no setup guidance; no direct (OIDC) login option.
- **Action:** new `integration.telegram_login` setting (master/customer switches, bot-approval options, OIDC Client ID + Fernet-encrypted Client Secret); `PUT /admin/integrations/telegram`, `POST /admin/integrations/telegram/test`, `telegram` key in `GET /admin/integrations`, public `GET /auth/telegram/config`; new OIDC login (`telegram_oidc*.py`: Authorization Code + PKCE, signed one-shot flow cookie, JWKS-verified `id_token`, account keyed by the `id` claim); bot-approval flow now reads the panel config (env stays the default); new admin Settings card with a full setup guide; store-web shows buttons per config and handles `?tg_error=`; docs `TELEGRAM-LOGIN-SETUP-FA/EN.md`; tests `test_r01_telegram_login_settings.py`, `test_p01_telegram_web_login.py` fixture gained `system_settings`.
- **After:** no migration; Caddy/CSP unchanged. Full API suite passes with the new tests; both web apps build. Not run against live Telegram (no BotFather credentials in the sandbox): the exact Allowed-URL matching and the `nonce` echo of Telegram's manual flow are verified only by a real login.
- **Ref:** this commit

### 2026-10-17 - Claude (with owner) - Telegram login: review pass R02 (hardening, diagnostics, UI)
- **Before:** the OIDC flow cookie was signed with the same key as other app tokens; a rejected Client Secret looked like a generic failure to both customer and admin; the panel badge ignored the "customer login" switch and described unsaved form values; the connection test did not check the site URL or a missing bot username and could return HTTP 500 on odd Telegram replies; after a failed redirect the visitor landed on the page with only a toast; the storefront Telegram buttons were inline markup with low-contrast text.
- **Problem:** see above - none is a data-loss bug, but each makes a real outage hard to diagnose or a misconfiguration look like success.
- **Action:** flow cookie now uses its own HMAC-derived key; token-endpoint failures are classified (5xx = unreachable, invalid_client = credentials rejected, logged as `tg_oidc_rejected` with Telegram's error code and shown to customers only as "unavailable"); `/telegram/test` adds site-URL (https, not localhost) and enabled/store_login checks, fails on a missing bot username, tolerates non-JSON/5xx replies; admin card shows per-method readiness from the SAVED config, "unsaved changes" state, disables test while dirty, validates the lifetime range, can copy all Allowed URLs; storefront: new `TelegramLoginButtons.jsx` (primary direct button, outlined bot fallback, busy state, bfcache-safe, AA-contrast `btn-tg`), login dialog reopens after a failed/denied redirect; `origin_mismatch` message added.
- **After:** new `tests/test_r02_telegram_oidc_hardening.py` (20 tests); full API suite and `vite build` for both apps pass; screenshots checked (light/dark, phone/desktop). Not run against live Telegram.
- **Ref:** this commit
