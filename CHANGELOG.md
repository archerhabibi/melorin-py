# Changelog

- `@melorin/api-client`: متد `raw(path, init)`؛ `authFetch` و `useCall` در admin-web روی آن اجرا می‌شوند (ترنسپورت واحد).

All notable changes to Melorin. The detailed, dated engineering log lives in
[docs/06-ARCHITECTURE-DECISIONS.md](docs/06-ARCHITECTURE-DECISIONS.md) ("Melorin Change Log"); this file is the short,
release-oriented summary. The project is pre-release: breaking changes are allowed.

## [Unreleased] - 2026-11-27

### Admin web: payments screen redesigned as a four-tab hub
- The «پرداخت‌ها» menu was one endless page (KPIs, review queue, list, bank-SMS settings and inbox, fast receipt review, duplicate-picture policy, gateway settings, OCR). It is now a hub with four tabs, split by what the admin is doing: **تراکنش‌ها** (KPIs, receipts waiting for a decision, filters, list, refunds), **رسیدها** (fast review and provisional approval, duplicate-picture policy, OCR), **پیامک بانک** (automatic card-to-card verification) and **درگاه‌ها** (card and Zarinpal of the main store, forms always open instead of an accordion at the bottom).
- Deep links: `#/payments`, `#/payments?tab=receipts|sms|gateways` (an unknown tab falls back to transactions). The transactions tab shows how many receipts wait for a decision and the receipts tab how many provisional charges wait for a final one, so urgent work is visible from any tab.
- Each tab fetches only its own data (gateway destinations and bank SMS are not requested while the admin looks at transactions); the payments list, the main store lookup and the typed receipt download are shared by the hub (`usePaymentsData.ts`). `BankSmsPanel` no longer embeds `ReceiptReviewPanel`.
- No API or permission change. Tests: `payments-hub.test.jsx` (tabs, badges, deep links, lazy loading per tab); typing ratchet lowered to 1956.

### Installer: one-line install redesigned (get.sh, melorin.sh, install_server.sh)
- `get.sh` is a function-wrapped bootstrapper (a truncated download does nothing), re-runs itself through sudo, checks apt/OS/network, installs the prerequisites with a lock- and dialog-safe apt, clones atomically with retries, accepts only strict `vX.Y.Z` release tags and a full 40-char `--commit` pin, and sets `core.fileMode=false` (its own `chmod +x` used to leave the checkout git-dirty).
- Unattended mode: `melorin install --domain D --admin-domain A --email E --yes` (bot token via `MAIN_BOT_TOKEN` / `--bot-token-file`, never argv); inputs and DNS are validated before anything starts. `melorin doctor` is a read-only check of the server and the installation.
- No terminal (ssh without `-t`, cloud-init) no longer ends with exit code 0 and nothing installed: the menu explains and exits 2 (`has_tty` really opens `/dev/tty`).
- The install runs detached (`setsid`, log `/var/log/melorin-install.log`, lock, exit code file) and is followed live; a dropped connection no longer kills it, and the one-time admin password is saved to `/root/melorin-credentials.txt` before the build.
- Docker: Compose v2 plugin, minimum version and a running daemon are verified; installed from the official apt repository. Image builds stream live, retry network errors and explain Docker Hub rate limits, blocked registries, full disks and out-of-memory.
- Fixes: a repair re-run of an installed server no longer dies in `bootstrap`; `melorin update` exits 0 when already current and picks only `vX.Y.Z` tags; `ufw` is never enabled without a confirmed SSH port; `uninstall` refuses a non-checkout directory (a copied `melorin.sh` would have deleted its own folder).
- Not root with a password-protected sudo and no terminal (cloud-init, ssh without `-t`) now gets an actionable message instead of sudo's bare "a terminal is required"; the `doctor` help no longer claims it "installs nothing" (it fetches the project and the download prerequisites, but installs no Melorin component).
- Tests: `tests/contracts/test_one_line_installer.py` runs the scripts (truncated download, no-tty, validation, retry, port owner, failure hints).

### Telegram: mandatory channel membership (force join) for the main bot
- Admin switch «عضویت اجباری کانال» (system area): up to 5 public or private channels, custom message, membership cache, live preview and a Telegram check (bot must be a channel admin).
- Enforced by Core at `POST /auth/telegram/bot`: `403 CHANNEL_JOIN_REQUIRED` with the channels still to join; sign-up and referral are kept; fail-open when a channel cannot be read; reseller bots are never gated.
- Main bot shows a join screen with one link button per channel and «✅ عضو شدم»; a `/start` deep link received while gated is replayed after joining.

### Bank SMS: end-to-end typed API (admin-web + API contract)
- Core declares response models for every admin and reseller bank-SMS route (`BankSmsOverviewOut`, `BankSmsSourceSavedOut`, `BankSmsMessageOut`, `BankSmsTokenOut`, `BankSmsReconcileOut`); the OpenAPI snapshot and generated TS types now carry real bodies instead of `{}`, and `status` / `direction` / `matched_by` are literal unions. The save body types the tuning knobs (`BankSmsSettingsIn`); ranges and unknown keys are still rejected by `clean_settings` with `BANK_SMS_SETTING_INVALID`.
- admin-web `BankSmsPanel` reads every response from the generated types (no `Json`, no casts); `@melorin/web-kit/bankSms` has real `BankSmsForm` / `BankSmsSourceBody` types; shared `errMsg()` in `shared/kit.tsx` (also understands FastAPI 422 lists).
- Fixed: changing the status filter, pairing, ignoring or reconciling no longer wipes the unsaved settings form; stale or aborted loads cannot overwrite newer data; a 422 validation message is shown instead of the generic failure text.
- Tests: typed GET/PUT/POST requests, form preservation, 422 message, OpenAPI contract guard for all bank-SMS routes; typing ratchet lowered to 1993.

### Admin web: typed receipt downloads
- `@melorin/api-client` gets `rawGet(path, init)`: a typed GET for binary endpoints (receipt images). The path must exist in the OpenAPI snapshot, path parameters are required exactly when the operation declares them, `query` is typed, and a missing parameter is a rejected promise. It shares the bearer-token / single-refresh transport with every other verb.
- Payments screen: the three receipt viewers (payment list, drawer, receipt-review queue) use that typed download and one `openBlobInTab` helper instead of hand-built `/api/v1/admin/payments/${id}/receipt` strings; the drawer ignores a download that finishes after the admin moved to another payment; the destinations effect depends on the typed client it actually uses.

### Zarinpal refund credential (fix/zarinpal-refund-credentials)
- The Zarinpal `access_token` (needed only for refunds) can now be added, replaced and deleted from the admin payments screen and the reseller store settings; it stays write-only: the API only reports `has_access_token`.
- `store_config.upsert` validates Zarinpal secrets with a typed model (`ZarinpalSecretIn`, unknown fields refused): omitted/blank keeps the token, a value replaces it, `clear_access_token: true` deletes it, and replace + delete in one request is a 422 `PAYMENT_CONFIG_INVALID`. A refused request changes nothing (validation runs before the row is touched); the audit record carries `access_token_changed`.
- `GET /stores/{id}/reseller/payment-config` now uses the same view as the admin API (`merchant_id`, `has_access_token` for Zarinpal), and the reseller form no longer wipes `public_config` on save.

### Audit remediation (V-AUDIT / V01 reports)
- Worker job lock fails closed: when Redis cannot confirm the per-job overlap lock (not configured, error, timeout after 3 short attempts) the job does not run, `JobLockUnavailableError` reaches ARQ and `melorin_job_runs_total{outcome="lock_error"}` counts it; new alert `MelorinJobLockUnavailable`; `lock_ttl` must exceed `timeout`; the worker refuses to start without `MELORIN_REDIS_URL`; lock failures log one line instead of a traceback per tick.
- Receipt OCR is a worker job (`payments.receipt_ocr`, `modules/payments/ocr_job.py`), no longer part of the upload request (V01 V-21): the upload answers at once (`receipt_read.ocr_state = pending`), the per-store daily vision budget is spent in the worker, and the grace credit waits (`ocr_pending`, at most 1 h) for a pending reading.
- One outbound-address policy (`domain/netpolicy.py`): CGNAT, NAT64, 6to4, Teredo and mapped forms are refused; numeric hosts (`127.1`, `0x7f.1`, `2130706433`) are parsed; used by webhooks, domain verification and panel URLs (V-011).
- Webhook delivery resolves once (non-blocking), validates every address and connects to that address with the real SNI/Host; a refusal is a counted failure that auto-disables the endpoint instead of an endless re-claim (V-012, V-013, V-014).
- `admin_area_guard` fails closed for a customer session on an `/admin/` path (V-08).
- Second pass: an admin session is refused once the account's second factor was reset (V-07); a future-dated Telegram `auth_date` is refused (V-12); Zarinpal's echoed amount must equal the request (V-24); `telethon` added to `pyproject.toml` (V-01); wallet lock-order invariant documented (V-29).
- Installer: `melorin update` takes an encrypted backup before `alembic upgrade head` and prints the rollback command (V-020); `get.sh` explains a non-empty non-git `APP_DIR` (V-33); the Dockerfile verifies the PGDG key fingerprint (V-04/V-025).
- Tests: the admin route walk now reads the real OpenAPI route table and pins the owner-only families (V-09/V-10).
- Order/ticket codes work on SQLite (dev default) as well as PostgreSQL sequences (V-26).
- Installer: no hidden commit pin (newest tag, else `main`); `melorin update` moves to the newest release tag; `secrets/` is git-ignored and `secrets_init` creates the bind-mounted files so Compose never creates directories (V-32, V-32a, V-34, V-35).
- Web nginx: 6 MB bodies, 404 for missing assets, gzip; Prometheus lifecycle endpoint off (V-008, V-009, V-024).
- Alerts: `MelorinApiDown` and `MelorinAlertSeriesAbsent`; the main Telegram bot idles (healthy) when no token is configured (V-006, V-005).
- Python 3.12 is enforced at import (V-02); grace credit has a `min_account_age_hours` setting and needs a proof signal (V-22).
- Third pass: the OCR base URL goes through the shared outbound policy at save time and (resolved, non-blocking) before every vision call (V-021); a per-store daily cap (`MELORIN_RECEIPT_OCR_DAILY_CAP`, default 300) stops a customer burning the paid OCR budget (V-21); a failed Google sign-in also drops the single-use nonce cookie (V-11).
- API runs 2 uvicorn workers by default (`MELORIN_API_WORKERS`) with a concurrency limit and 2 concurrent KDFs per process (V-028); CI gets a SQLite lane (V-40) and a gitleaks allow-list for fake fixtures (V-029).

- Fourth pass (remaining V-AUDIT gaps): the admin bootstrap validates the e-mail with the same `email-validator` the login schema uses and the installer menu refuses `.test/.local/.invalid/.onion` up front, so an install can no longer create an admin who is locked out with HTTP 422 (V-004); in external-proxy mode the post-install check probes the loopback ports instead of `https://<domain>/` (no more ~1 min false warning per domain) and the "reseller bots disabled by default" message is corrected (V-010); backup checksums store the archive basename and the drill/verify scripts check from the archive's directory, and the restore drill now also requires an `alembic_version`, a non-empty `users` table and the same revision as the live database (V-027); `target="_blank"` links all carry `rel="noopener noreferrer"` (V-030); the compose memory comment states the 3584 MiB steady-state budget vs. the 3856 MiB sum of every cap (V-05).

- Fifth pass (last open V-AUDIT items; V-023/V-024 image refresh and container hardening are deliberately deferred): a refresh token is bound to the client family that received it (user-agent with version numbers stripped), so a token replayed from another kind of client burns the whole family instead of minting one free pair, while a browser auto-update keeps its session (V-06); the 2-second `poll_tick` heartbeat no longer writes two log lines per run, failures stay visible (V-026); `pyproject.toml` now declares `tzdata` and a unit test keeps it equal to `requirements.in` (V-01); the Caddy CSP `connect-src` is `'self'` plus Google sign-in instead of any https origin (set it for a separate API origin, `VITE_MELORIN_API_URL`) (V-032); the API image copies only the backup/restore scripts it runs (V-025); the installer ends with a loud warning when no off-site backup target is set (V-027); `melorin update` can require a signed release tag (`MELORIN_REQUIRE_SIGNED_TAGS=1`, `git verify-tag`) (V-020); the deliberate missing `-e` in `melorin.sh` is documented (V-036).
- Sixth pass (closure): documented the silent-sign-in network heuristic (V-13), Idempotency-Key retry semantics (V-25) and the `/metrics` CSP (V-38) in `docs/12-SECURITY-AUTHORIZATION.md`; full API suite re-run green (2798 passed, 11 skipped). V-023/V-024 remain deliberately deferred.

- Seventh pass (V-006 remainder): `scripts/host_watch.sh` is an out-of-stack watchdog installed with ops-watch (cron, every 5 min): it messages Telegram directly when disk or RAM run low, when any Compose service (API, worker, main/reseller bots, db, redis) is down or unhealthy for more than 10 minutes, or when a TLS certificate is close to expiry, so a dead API/Prometheus or a permanently broken main bot can no longer go unnoticed; the installer ends with a loud warning when no alert receiver is configured. The full API suite was run on PostgreSQL for the first time (2811 passed, 1 skipped; `tests/postgres` 12/12 with the migration baseline), closing the open V-031 lane. Closure table: docs/21-ROADMAP-TECHNICAL-DEBT.md.

- Eighth pass (V-022 remainder, V01 V-21/V-22 regressions): the grace-credit sweep now also refuses a receipt whose uploader network (keyed HMAC tag of the IPv4 / IPv6 /64, never the raw address; website sessions only, because a bot session arrives from the bot container) already holds `max_open_per_origin` (default 2) open provisional credits or a revoked one (`origin_open_limit`, `origin_revoked_before`), closing the "fresh account bypasses the per-user guard" gap; admin panel field added. A known duplicate-image verdict now wins over `ocr_pending`, and the receipt tests no longer depend on `tesseract` being installed (conftest forces the OCR engine off).
- Ninth pass (V-023/V-024, no Docker daemon was available to run containers, so only statically verifiable parts were done): Postgres, Redis and both web containers now drop every capability (`cap_drop: [ALL]`, plus only the documented `cap_add` set), refuse privilege gain, and the web containers run with a read-only root and tmpfs for nginx state; the bridge subnet is `MELORIN_SUBNET` (default `172.28.0.0/16`) and the installer picks the first candidate that overlaps no host route and writes the matching `MELORIN_TRUSTED_PROXY_IPS`; a weekly Trivy workflow (`image-scan.yml`) reports fixable HIGH/CRITICAL findings in the pinned base images next to Dependabot's digest bumps. Not done on purpose: swapping nginx for `nginx-unprivileged` (no digest could be resolved offline) and narrowing `env_file: .env` per service (every service validates the full production settings, so it needs a live Compose run). `docker compose up` on a real host is the first test of the cap sets.

## [Unreleased] - 2026-11-18

### Security / reliability
- Local rate-limit fallback is bounded (monotonic clock, per-key window, sweep, 10,000-key cap) (audit M-04).
- `/health` reports `rate_limit: fail_closed` in staging/production when Redis is down (M-11).

### Payments
- **Breaking (schema):** new `refund_operations` table in the baseline migration; recreate development databases.
- Gateway refunds are a durable three-phase workflow with idempotency, lease and state machine; the gateway is never called
  inside a locked transaction (M-10).
- `refund_recovery_job` finishes interrupted refunds without a second gateway call; unknown gateway outcomes go to
  `manual_review`; manual-card refunds answer `409 REFUND_NOT_SUPPORTED` instead of a 500 (M-03).

### CI / tooling
- Web E2E (Playwright) is a blocking CI job (M-05).
- `npm audit`: runtime dependencies block at `high`, dev tooling at `critical` while picomatch (GHSA-fc5q-39xc-vjpf) has no
  patched release (ADR-R2).
- `scripts/gen_docs.py` fails with an explicit "install the API dependencies" message instead of a bare ImportError (M-02).

### Verification
- PostgreSQL lane incl. real-lock refund concurrency test, Compose stack from an empty DB and `scripts/e2e_smoke.py` pass on a real host (details in docs/06).
- `deploy.yml` diagnoses SSH/secret problems before the deploy step instead of a bare exit 255 (M-09).

### Docs
- ADR-R1 (open business decisions: refund, commission, FX, identity), refund workflow in docs/15, regenerated `docs/STATUS.md`.
