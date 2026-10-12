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
