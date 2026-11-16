# تست، کیفیت و انتشار / Testing, Quality & Release

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** تست‌ها، CI، کیفیت و شواهد انتشار.

**لایه‌ها:** تست واحد/سرویس/قرارداد/HTTP؛ مسیر PostgreSQL (`TEST_PG_URL`، تست‌های concurrency)؛ تست‌های فرانت (vitest) و E2E با Playwright.

**دروازه‌های کیفیت (`make lint`, `make test`, `make quality-gate`):** ruff check/format، mypy، import-linter (۸ قرارداد)، bandit، `gen_docs --check`، حداقل پوشش، بودجهٔ بستهٔ فرانت.

**واقعیت استقرار (2026-11-16):** مجموعهٔ کامل API شامل ۲۷۱۱ تست پاس و ۱۲ skip؛ baseline روی Postgres خالی با `alembic upgrade head` و `alembic check` بدون تفاوت با مدل‌ها.

**مسیر انتشار:** بدون شواهد staging و ماتریس release تصمیم انتشار گرفته نمی‌شود (`scripts/check_release_matrix.py`). ناموفق‌ها و اجرا نشده‌ها در «مواد ادغام‌شده» با جزئیات ثبت شده‌اند.

**اسناد تولیدشده:** `docs/STATUS.md` و `docs/API.md` خروجی `python scripts/gen_docs.py` هستند؛ دستی ویرایش نشوند، و `gen_docs.py --check` در CI انحراف را می‌گیرد.

## English section

**Purpose:** tests, CI, quality and release evidence.

**Layers:** unit/service/contract/HTTP tests; a PostgreSQL lane (`TEST_PG_URL`, concurrency tests); frontend tests (vitest) and Playwright E2E.

**Quality gates (`make lint`, `make test`, `make quality-gate`):** ruff check/format, mypy, import-linter (8 contracts), bandit, `gen_docs --check`, coverage floors and the frontend bundle budget.

**Latest evidence (2026-11-16):** the full API suite passed with 2711 tests and 12 skipped; the baseline on empty Postgres passed `alembic upgrade head` and `alembic check` with no difference from the models.

**Release path:** no release decision is made without staging evidence and the release matrix (`scripts/check_release_matrix.py`). Failures and not-run items are recorded in the merged material.

**Generated docs:** `docs/STATUS.md` and `docs/API.md` are the output of `python scripts/gen_docs.py`; they are never edited by hand and `gen_docs.py --check` rejects drift in CI.

## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `20-TESTING-QUALITY-RELEASE.md`

#### استراتژی تست و کیفیت
##### انواع تست
Unit: pricing، Debt Limit، state transitions، Ledger و authorization. Integration: PostgreSQL، Redis، jobs، storage و adapters. Contract: Channel ↔ Core، Payment Adapter، Sanaei و PasarGuard. همچنین E2E، Security، Concurrency و Resilience.
##### E2E اجباری
Registration/Login/Linking؛ Guest Checkout؛ callback پرداخت تکراری؛ Wallet؛ Main purchase؛ Reseller purchase؛ Debt Limit؛ provisioning success/failure/retry؛ refund و commission reversal؛ Test Account هم‌زمان؛ Ticket/attachment؛ notification retry؛ reconciliation؛ API credential disable/rotate؛ Backup/restore.
##### Concurrency
دو خرید از یک Wallet، خرید هم‌زمان در آستانه Debt Limit، callback تکراری، Test Account موازی، دو Provisioning Retry هم‌زمان، Coupon محدود و redemption هم‌زمان، شارژ Store-scoped و تحویل/retry Webhook تست شوند. تست‌ها باید اثبات کنند که هر خرید فقط از Wallet همان Store برداشت می‌کند و هر Reseller فقط مشتریان/Couponهای Store خود را می‌بیند. DB constraints و idempotency جزو شواهد صحت هستند.
##### CI Quality Gates
Lint/type checks، Unit/Integration tests، OpenAPI diff، migration test، dependency/security scan و build. Contract tests برای هر Adapter اجرا شوند.
##### Definition of Done
وضعیت هر قابلیت: SPECIFIED → IMPLEMENTED → TESTED → PRODUCTION VERIFIED. عملیات مالی، Identity، Store authorization و Provisioning به E2E و Security test نیاز دارند.

##### M7.7 — مسیر تست PostgreSQL / PostgreSQL test lane

- پیش‌فرض: تست‌های واحد روی SQLite درون‌حافظه (سریع و hermetic).
- با تنظیم `TEST_PG_URL=postgresql+asyncpg://melorin:test@localhost:5432/melorin` همان تست‌ها روی PostgreSQL اجرا می‌شوند؛ هر تست یک schema موقت و جدا می‌گیرد (`apps/api/tests/_db.py`).
- `tests/test_postgres_concurrency.py` فقط در این مسیر اجرا می‌شود: برداشت موازی بدون اضافه‌برداشت، و کلید idempotency یکسان که فقط یک‌بار ثبت می‌شود (`FOR UPDATE` در SQLite بی‌اثر است).
- در CI جاب `postgres-lane` این مسیر را اجرا می‌کند.
- Run locally: `cd apps/api && TEST_PG_URL=... pytest -q -m "not integration"`.

##### Phase 4 — layout, coverage gate and frontend tests

- **Backend test names are feature-based** (`test_payments_service_db.py`, `test_channel_binding.py`, ...), no sprint codes. They stay flat in `apps/api/tests/` because the helpers (`_db`, `_http`) are imported by module name and several contract tests resolve paths from `__file__`. The old-name → new-name mapping is in the body of commit `test(phase-4.7)`.
- **HTTP harness** (`tests/_http.py`): drives the real FastAPI app through `httpx.ASGITransport` with a per-test schema (SQLite by default, PostgreSQL with `TEST_PG_URL`). Use it for route-level behaviour (status codes, error envelope, cookies, dependencies). Service-level tests keep using `_db.open_session`.
- **Coverage gate**: CI runs `pytest -m "not integration" --cov-fail-under=75` (measured 85.9 % in that lane). `tests/test_ci_coverage_strategy.py` only lets the number go up. Coverage is measured with `concurrency = ["greenlet", "thread"]`; without it the lines after an awaited DB call are not traced and routes look under-covered.
- **Frontend**: `npm test` (Vitest + Testing Library, jsdom) in `apps/store-web` and `apps/admin-web`, run by CI before `npm run build`. Tests live in `tests/` next to `src/` (not inside it, so source-scanning guards and the production bundle are unaffected). They cover the in-memory session token, the admin `authFetch` refresh logic (single shared refresh, no retry loop), status/format helpers, dialogs, theme and the shared catalog helpers. A browser-level smoke (login → buy → account) needs the full stack and is not part of this lane.

### منبع / Source: `20-TESTING-QUALITY-RELEASE.md`

#### Melorin Release Evidence Matrix

This is the authoritative release-status document. Older phase/F finding reports are historical change records; they must not be read as production approval. A capability is only release-ready when all four evidence columns are green.

| Area | Implemented in source | Static-tested | Runtime-tested | Production-evidenced | Current decision |
|---|---:|---:|---:|---:|---|
| API/Core startup and dependencies | Yes | Yes | Yes (2026-10-10, local PG16/Redis7, full E2E) | No | Blocked |
| Explicit Alembic baseline and upgrade | Yes | Yes | Yes (fresh DB to the head of that day, `alembic check` clean; current head: `docs/STATUS.md`) | No | Blocked |
| Store/Admin Web routing and API contract | Yes | Yes | Yes (headless Chromium vs live API) | No | Blocked |
| Deterministic Web lockfiles/build | Yes | Yes | Yes (`npm ci` + build; Docker image build not run) | No | Blocked |
| Telegram Main/Reseller runners | Yes | Yes | No | No | Blocked |
| Payment refund adapter and wallet reversal | Yes | Yes | No | No | Blocked |
| Encrypted scheduled backup | Yes | Yes | Partial (manual backup + restore drill passed; schedule not run) | No | Blocked |
| Provider/TLS/DNS safeguards | Yes | Yes | No | No | Blocked |
| PostgreSQL finance concurrency | Yes | Yes | Partial (sequential wallet flow only) | No | Blocked |
| Metrics and Prometheus scrape config | Yes | Yes | Partial (`/metrics` served; Prometheus not run) | No | Blocked |

##### Evidence rules

- **Implemented in source** means the behavior exists in the canonical repository and has a clear owner/boundary.
- **Static-tested** means compile, AST, source contract, shell, lockfile, or configuration checks passed.
- **Runtime-tested** means the relevant service actually started and the behavior was exercised against its real dependency.
- **Production-evidenced** means staging/production-like credentials, deployment, monitoring, recovery, and operational logs exist.

##### Runtime evidence log

- 2026-10-10 (local, PostgreSQL 16, Redis 7, Python 3.13, Node 22): `alembic upgrade head` on an empty database, `alembic check`, `python -m melorin.cli bootstrap` (twice, idempotent), API + ARQ worker, `scripts/e2e_smoke.py` (top-up, approval, wallet purchase, mock provisioning, one VPN account, outbox drained, worker heartbeat, XFF-rotation brute force throttled), outbox replay without duplicate accounts, `npm ci` + build of both web apps, headless-browser login and dashboard, encrypted backup + `backup_restore_drill.sh` (47 tables restored).
- Not run: Docker image builds/Compose (no daemon), Telegram bots against the Bot API, Zarinpal sandbox, real Sanaei/PasarGuard panels, Prometheus.
- 2026-11-15 (r15, Ubuntu 24.04, Docker 29, Compose 2.40, branch refactor/audit-r15-impl): all 8 images built; bare `compose up` ran the one-shot `migrate` before api/worker/backup; `scripts/e2e_smoke.py` on the real stack ALL PASSED; Playwright 24 passed / 2 skipped; real encrypted backup + `backup_restore_drill.sh` + `backup_restore_verify.sh` passed (76 tables). Restore drill found and fixed a pg_dump 17 vs server 16 mismatch (docs/06-ARCHITECTURE-DECISIONS.md r15). Not run: Telegram bots, Zarinpal sandbox, real PasarGuard/Sanaei panels, Caddy/Prometheus/Alertmanager.
- 2026-10-18 (M7.3): `scripts/runtime_evidence.py` added (see [Runtime evidence collector](#runtime-evidence-collector-m73)). It is fail-closed and was **not run against real systems** in that change; the items above are still not run and no matrix cell was changed.

##### J01-J19 remediation status

This table tracks implementation and evidence separately. A completed code change does not make a row runtime-tested or production-evidenced.

| Finding | Remediation now in source | Static evidence | Runtime evidence | Production decision |
|---|---|---|---|---|
| J01 | Python pins upgraded; pip-audit CI gate; Dependabot enabled | Compile and config checks passed | CI package install/audit required | Blocked |
| J02 | CIDR-aware trusted proxy resolver; fixed Compose proxy subnet | Resolver and config checks passed | Through-Caddy staging test required | Blocked |
| J03 | Savepoint-protected order insert and winner recovery | Regression contract added | PostgreSQL concurrent order test required | Blocked |
| J04 | Closed environment enum; Fernet, CORS and public URL validation | Settings contract added | Startup matrix required | Blocked |
| J05 | Unit/integration/concurrency matrix; coverage XML and CI floor | Test strategy contracts passed | Full CI integration run required | Blocked |
| J06 | Staging evidence command; Compose healthchecks; provider probes | Shell/config checks passed | Staging bundle required | Blocked |
| J07 | Atomic Redis pipeline; bounded local degraded limiter | Redis policy regression added | Redis outage test required | Blocked |
| J08 | Readiness returns 503 unless DB, Redis and fresh worker heartbeat pass | Readiness and Compose checks passed | Failure-injection staging test required | Blocked |
| J09 | Metrics bearer token; terse public health; protected Prometheus scrape | Endpoint/config contracts passed | Authenticated scrape test required | Blocked |
| J10 | scrypt hashing moved off event loop with `asyncio.to_thread` | Async call-site contract passed | Load/latency test required | Blocked |
| J11 | Mandatory admin 2FA and persisted TOTP replay counter; role metadata migration | Security contracts passed | Login/replay integration test required | Blocked |
| J12 | Fixed HTTPS `MELORIN_PUBLIC_API_URL` for payment callbacks | Callback-origin contract passed | Gateway sandbox callback test required | Blocked |
| J13 | Build tooling moved to devDependencies; npm audit CI gate | Manifest/lockfile checks passed | npm audit/build CI required | Blocked |
| J14 | Reports and referral routers added; commission rules/history exposed | Route contracts passed | API integration test required | Blocked |
| J15 | Multi-store reseller bot config with isolated state; Core-only operations | Runner contract passed | Telegram Bot API multi-store test required | Blocked |
| J16 | Alert state for DB, Redis, worker, panels and outbox; Prometheus rules | Alert/config checks passed | Prometheus/Alertmanager test required | Blocked |
| J17 | Explicit CORS origin/method/header allowlists; wildcards rejected outside dev | CORS contract passed | Browser preflight staging test required | Blocked |
| J18 | HttpOnly refresh cookie; memory-only access token; reload recovery | Session contract passed | Browser cookie/refresh test required | Blocked |
| J19 | Ruff E/I/UP/B policy, format check, local/CI consistency guard | Quality config check passed | Full CI lint run required | Blocked |

**J01-J19 status:** source remediation is present and static evidence is recorded; no item is marked runtime-tested or production-evidenced by static checks alone.

##### Current release decision

**RELEASE BLOCKED.** The repository has meaningful source and static evidence, but Docker/Compose, Telegram, payment providers, panel providers and any production-like environment have no runtime evidence yet.

##### Required promotion path

1. Run `scripts/install_verify.sh` in a runner with package-registry access.
2. Run `scripts/migration_smoke.sh` against fresh and upgraded PostgreSQL.
3. Run `npm ci`, both Web builds, and all Docker image builds.
4. Start Compose with PostgreSQL, Redis/ARQ, API, Web, Telegram and Prometheus.
5. Execute payment/provider/Telegram/finance-concurrency smoke suites.
6. Execute encrypted backup, off-host copy, decrypt, restore and integrity checks.
7. Run `python scripts/runtime_evidence.py --allow-mutation` (Telegram, Zarinpal sandbox, panels, Docker, Caddy, Prometheus/Alertmanager); attach `var/evidence/m73-*/summary.json`.
8. Attach timestamped logs and update only the evidence columns that actually passed.

##### Runtime evidence collector (M7.3)

`scripts/runtime_evidence.py` gathers the evidence that unit tests cannot provide and that
[`20-TESTING-QUALITY-RELEASE.md`](20-TESTING-QUALITY-RELEASE.md) requires before any "Runtime-tested" cell may turn green.

**It is fail-closed.** A check without its prerequisites is `skipped` (with the reason), never `passed`; any skipped
check makes the exit code non-zero (3) unless `--allow-skip` is given; a failure exits 1. Secrets are masked in
`summary.json`, `summary.md` and logs. Nothing in the repository claims these checks have already run.

```bash
python scripts/runtime_evidence.py --list
python scripts/runtime_evidence.py --only telegram_main,zarinpal_sandbox
python scripts/runtime_evidence.py --allow-mutation        # everything that is configured
make evidence                                                # same, via Makefile
```

The bundle is written to `var/evidence/m73-<UTC timestamp>/` (`summary.json`, `summary.md`, build/validate logs).
Attach it to the release record and flip only the matrix cells whose checks are `passed`.

| Check | Proves | Needs |
|---|---|---|
| `telegram_main` | Main bot token is valid (`getMe`) and no webhook blocks long polling | `MELORIN_TELEGRAM_TOKEN` |
| `telegram_reseller` | Same for a reseller bot | `MELORIN_TELEGRAM_RESELLER_BOT_TOKEN` |
| `zarinpal_sandbox` | `request.json` returns a sandbox StartPay URL; cancelled, unpaid and forged callbacks never verify | `MELORIN_ZARINPAL_SANDBOX_MERCHANT` (any sandbox merchant UUID) |
| `panel_roundtrip` | health, create, read, extend, suspend/resume, revoke and "gone" on each real panel (Sanaei, PasarGuard) | `MELORIN_EVIDENCE_PANELS` (JSON file path) and `--allow-mutation` |
| `docker_build` | `docker compose config` and all three image builds | docker CLI/daemon |
| `caddy_config` | `infra/Caddyfile` validates (including the on-demand TLS block) | `caddy` or docker |
| `tls_ask_gate` | `/api/v1/tls/ask` answers 200 for an active reseller domain and 404 for everything else | `MELORIN_EVIDENCE_API_URL`, `MELORIN_EVIDENCE_RESELLER_DOMAIN` |
| `prometheus_rules` | `infra/alerts.yml` passes `promtool check rules` | `promtool` or docker |
| `prometheus_scrape` | Prometheus scrapes `melorin-api` (`up == 1`) and loaded the `melorin-core` rule group | `MELORIN_PROMETHEUS_URL` |
| `alert_delivery` | A synthetic alert pushed to Alertmanager reaches the receiver | `MELORIN_ALERTMANAGER_URL`, `MELORIN_ALERT_RECEIVER_PROBE_URL` |

`MELORIN_EVIDENCE_PANELS` example (credentials stay in the file, never in the bundle):

```json
[{"name": "tehran-1", "kind": "pasarguard", "base_url": "https://panel.example.com",
  "credentials": {"username": "admin", "password": "..."}, "config": {"group_ids": [1]}}]
```

Not automatable here and therefore recorded by hand: a real card payment in the Zarinpal sandbox (needs a browser),
the first real certificate issued for a reseller domain (needs public DNS), and Telegram end-to-end conversations.

### منبع / Source: `20-TESTING-QUALITY-RELEASE.md`

#### r23 full verification (2026-11-16, Ubuntu 24.04, Docker 29, Chromium)

| Lane | Result |
|---|---|
| lint-imports / ruff / ruff format / mypy (384 files) | clean, 8 contracts kept |
| make guards (G001-G010, quality config, ops P0, gen_docs --check) | passed; current head: `docs/STATUS.md` |
| API suite (SQLite) | 2709 passed, 12 skipped, 2 failed before fix; the 2 (plus 1 identity-review contract) were stale file-path assertions after the admin-web splits, fixed in tests |
| admin-web tsc, eslint, vitest, build | clean, 309 passed |
| store-web lint, vitest, build | clean, 83 passed |
| api-client tests | 6 passed |
| alembic upgrade head on empty PostgreSQL 16, re-run, check, downgrade base, upgrade | ok, no drift, 82 tables |
| Docker compose full stack (11 services, healthy) + scripts/e2e_smoke.py | ALL PASSED (32 checks) |
| Playwright (Chromium) | 24 passed, 2 skipped |
| PostgreSQL lane (tests/postgres, tests/http) | started, not finished in this session |

Finding: infra/ files created with umask 077 keep Alertmanager unhealthy until `chmod -R a+rX infra` (environment issue).

#### r21 full test run (2026-11-15, Ubuntu 24.04, Docker, Chromium)

| Lane | Result |
|---|---|
| lint-imports / ruff / mypy (371 files) | clean, 8 contracts kept |
| API unit suite | 2728 passed, 1 skipped |
| admin-web tsc, eslint, vitest | clean, 309 passed |
| Playwright (Chromium, mocked API) | 24 passed, 2 skipped (need a seeded staging stack) |
| Docker: rebuild + upgrade of an existing r15 database to the current head (see `docs/STATUS.md`) | all services healthy |
| Live smoke scripts/e2e_smoke.py (API + worker + Postgres + Redis, mock panel) | ALL PASSED (32 checks) |
| PostgreSQL 16 lane (TEST_PG_URL) | 8 passed |
| integration + concurrency (PG 16 + Redis 7) | 11 passed, 1 skipped |
| alembic upgrade head from empty, alembic check | current head (see `docs/STATUS.md`), no drift |
| test_deploy.sh, test_restore_drill.sh | passed |

##### Findings
- Alertmanager restart loop (permission denied on the entrypoint bind mount) when the checkout dir and infra/ are mode 0700. Environment issue, fixed with chmod 755 on the checkout and infra/. No code defect.
- No code defects found by any lane.

##### Not run
Real PasarGuard panel, real Telegram bots, Zarinpal, Caddy TLS profile, real backup restore with age, the 2 seeded-stack Playwright tests.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
