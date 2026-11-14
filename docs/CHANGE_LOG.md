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

> Entries before 2026-11-09 were archived (T-R12) and live in git tag `changelog-archive-2026-11-09` (`git show changelog-archive-2026-11-09:docs/CHANGE_LOG.md`), per DOCUMENTATION-POLICY.

## 2026-11-12 - Admin team: invite admins with roles to the web panel
- **Area:** api / admin-web / identity / docs
- **Before:** every admin-panel user was all-powerful and the only way to add one was the CLI bootstrap; there was no role, no invitation and no way to take access away.
- **Problem:** the owner could not give an accountant, a support agent or a viewer their own login without handing over everything.
- **Action:** roles (owner, manager, finance, support, viewer) over permission areas enforced server-side by a path->area table (`domain/admin_access.py`, unknown paths owner-only, empty role = no access); one-time hashed invite links (72h) where the invitee sets their own password and authenticator (`/auth/admin-invite/*`); owner screen "مدیران سامانه" (invite, change role, suspend, reset access, revoke sessions, remove) and "حساب من" for everyone; self-protection and last-owner protection; migration `0055_admin_team` back-fills existing admins as owner. Design: `docs/24-Admin-Team-Design.md`.
- **After:** the owner can add admins from the panel with least-privilege roles; every denial is audited; existing admins keep full access.

## 2026-11-12 - Persian Telegram alerts; first backup at install
- **Area:** infra / scripts / ops
- **Before:** Telegram alerts were Alertmanager's default English dump (labels, annotations, an internal Prometheus "Source:" link), and the critical `MelorinBackupStale` alert fired about 10 minutes after every install (no backup exists until the 02:00 UTC schedule), then "resolved" by itself.
- **Problem:** hard to read for an Iranian operator; a false critical alarm on every fresh install.
- **Action:** every rule in `infra/alerts.yml` has `summary_fa` and `hint_fa`; `alertmanager-entrypoint.sh` renders a Persian message template (severity, what happened, panel/server/job, hint, start/end in Iran time, no internal link; English summary is the fallback); `post_install.sh` takes the first backup immediately.
- **After:** one readable Persian message per alert group; no false backup alarm after install.

## 2026-11-12 - HTTPS did not come up after repeated installs (Let's Encrypt rate limit); Redis overcommit
- **Area:** infra / scripts / ops
- **Before:** after several installs of the same domains the post-install check printed "did not answer 200 (got '000')" with no explanation, and the sites had no certificate.
- **Problem:** `melorin uninstall` ran `compose down -v`, which also deleted the `caddy_data` volume (certificates + ACME account), so every reinstall requested new certificates; Let's Encrypt allows 5 per exact hostname set per 7 days (HTTP 429, retry-after shown in the Caddy log). Caddy had no ACME e-mail, so its ZeroSSL fallback never registered. Redis warned that `vm.overcommit_memory` is 0.
- **Action:** Caddyfile sets `email` (from the admin e-mail, passed as `MELORIN_ACME_EMAIL`); uninstall now keeps the certificate volumes; `post_install.sh` explains why HTTPS fails (rate limit with retry time / port 80 unreachable / other issuance error), waits 60 s instead of 30 s, and sets `vm.overcommit_memory=1` persistently.
- **After:** a reinstall reuses the stored certificate. ZeroSSL refuses `.ir` hostnames, so for `.ir` the only CA is Let's Encrypt and an already exhausted limit can only be waited out.

## 2026-11-11 - Installer wires the Telegram alert receiver; container logs are rotated
- **Area:** scripts / ops / docs
- **Before:** `install_server.sh` never set `ALERT_TELEGRAM_BOT_TOKEN` / `ALERT_TELEGRAM_CHAT_ID`; no service had a log-rotation policy.
- **Problem:** found on a clean-server install (T05/T06): Alertmanager started with "no alert receiver configured", so every Prometheus alert was dropped even though the bot token and the admin's Telegram ID had been given to the installer. Docker's default `json-file` driver never rotates, so logs could slowly fill the disk.
- **Action:** when both bot token and admin ID are supplied the installer now sets the two `ALERT_TELEGRAM_*` keys; `melorin` menu 1 (bot token) and 5 (admin ID) keep them in sync unless a separate alert bot was configured. `docker-compose.yml` gets an `x-logging` anchor (`json-file`, 10m x 3) on all 12 services. Reports: `docs/T05..T08`.
- **After:** verified live: Alertmanager loaded the receiver without the warning and delivered a test alert to the admin's Telegram (`alertmanager_notifications_total{integration="telegram"}` = 1, all failure counters 0); `docker compose config` valid, `scripts/check_ops_p0.py` green; all 12 containers healthy after recreation with `max-size=10m, max-file=3`.

## 2026-11-09 - Panel backup verification works against a newer panel PostgreSQL
- **Area:** scripts / docs / ops
- **Before:** `scripts/verify_panel_backup.sh` always called the host's `pg_restore`.
- **Problem:** found live on the test host: the panel database is PostgreSQL 17, Ubuntu 24.04 ships `pg_restore` 16, so the check of a perfectly good archive failed with `unsupported version (1.16) in file header`.
- **Action:** optional `PG_RESTORE` (a command, e.g. `docker exec -i pasarguard-timescaledb-1 pg_restore`); the dump is read from stdin; a failure prints pg_restore's message plus a hint. Default behaviour is unchanged. RUNBOOK step 6 documents it.
- **After:** the latest real archive verified on the test host: checksum OK, age decrypt OK, 330 database objects, 9 data entries (certs included). Prometheus checked live after the `nobody` chown: target `up`, 4 rule groups / 21 rules, `melorin_panel_nodes` returns data.

## 2026-11-09 - PG-12: the store role name is the admin's choice; PG-05 proven on the live panel
- **Area:** api / tests / docs / ops
- **Before:** the store role was the fixed name `melorin-store`; `applied_role()` only recognised that exact name. PG-05 provision/rotate had never been run against a real panel.
- **Problem:** a store (or another deployment) may need its own role name; and "verified on fakes" is not "verified live".
- **Action:** `store_role.normalize_role_name` (default `melorin-store`; 2-32 chars `a-z 0-9 - _`; `owner`, `administrator`, `operator`, `melorin-service` refused, validated BEFORE any panel call). `apply {role_name}` creates that role and records `panel.config.admin_role` + `admin_role_managed`; `plan?role_name=` previews it; `revert` clears both. Admin-web/API client regenerated (`StoreRoleIn.role_name`). Live on the test panel (5.6.0): `rotate` run with a temporary owner key (created and deleted by the operator, never stored) - new service key verified as `melorin-service` before the switch, old key deleted, a stray service key left by an earlier attempt found and removed, panel health read with the new key.
- **After:** 127 tests of the affected area green (SQLite lane, run from the source tree); `gen_docs --check` clean; api-client typecheck + tests green.

## 2026-11-09 - Live proof on the test panel: three bugs only a real panel showed, branding verified end to end, panel backup complete
- **Area:** api / tests / docs / ops
- **Before:** PG-05, the `melorin-store` role, branding and the panel backup were verified on fakes only; the docs said "existing admins change on their next sync" and "unverified: how `custom_variables` reach the page".
- **Problem:** (1) `sync_all` only re-pushes unfinished rows and `ensure_admin` never sent `role_id`, so an admin that already existed never got the new role; (2) the service role lacked `admin_roles.read_simple` (403 on the role lookup); (3) rotate sent `token_urlsafe(32)` as the service admin's password, which the panel's password rule refuses when it has no special character (422, random); (4) the backup could not read the panel's `privkey.pem` (root, 0600) as the worker's non-root user.
- **Action:** `ensure_admin` moves an existing admin to the wanted role (never an owner); `store_role.apply/revert` flag the panel's admin rows for the next sync; `admin_roles.read_simple` added to the single capability table; service admin password built with `generate_password()`; ACL for uid 10001 on the panel cert directory (operator step, RUNBOOK). Live results: `ml_main` now holds `melorin-store` on the panel; rotate works repeatedly; branding applied for a test store -> a test user's subscription page shows brand name, support link and logo (so `user.admin.custom_variables` is the right path; the template needed no change); then reverted and the test user deleted. Panel backup now holds database + certs + templates (195 KB) and `verify_panel_backup.sh` passed (330 DB objects, 9 data entries).
- **After:** affected tests green (new: role move, owner untouched, password rule, flagged rows); ruff clean; temporary owner keys created for the proof were deleted; the old owner key `bot` is still active on the panel (revoke it there).

## 2026-11-09 - Mediator rework: verification pass (layering contract, near-expiry warning, formatting)
- **Area:** api / worker / tests / docs
- **Before:** `import-linter` reported the layers contract BROKEN on this branch (`vpn.manual_assign` imported `catalog.service`); `near_expiry_job` warned from Melorin's sold expiry alone, so an `on_hold` account (clock not started) or an account renewed on the panel could get a wrong "ends soon" notice; four PG-12 files were not `ruff format`-clean.
- **Problem:** the sold expiry is Melorin's entitlement, not the panel's "now"; a warning is a statement about "now".
- **Action:** `product_snapshot` moved to `domain/product_snapshot.py` (pure; `catalog` and `vpn` both use it, 6/6 contracts kept). `near_expiry_job` now nominates candidates from the sold expiry and sends only after a live read says the panel agrees (not `on_hold`, panel expiry inside the window); a panel that does not answer sends nothing and leaves the flag unset so the next run retries; accounts without a panel keep the sold expiry. New test `test_near_expiry_warning_is_sent_only_when_the_panel_agrees`. Formatting fixed.
- **After:** verified on this branch: backend suite 2319 passed / 10 skipped; mediator, live-view, manual-assign, connections and PostgreSQL concurrency tests also green on PostgreSQL 16; `alembic upgrade head` -> `downgrade 0050` -> `upgrade head` -> `alembic check` clean; `ruff check`/`format` clean; admin-web 212 and store-web 76 vitest tests pass, both lint (0 errors) and admin-web build pass.

## 2026-11-09 - PG-12: vetted base subscription template that reads the `melorin_*` variables
- **Area:** infra / docs / tests
- **Before:** branding values were written into the store admin's `custom_variables`, but nothing in the repo could display them.
- **Problem:** without an installed page template the "apply to panel" step changes nothing a customer sees. PasarGuard's docs say the subscription page is built from the admin's `sub_template` or the default template (Jinja) but do not say how `custom_variables` reach a template.
- **Action:** `infra/sub-template/index.html`: one fixed, operator-installed page (no script, no external request, CSP `default-src 'none'`, every value escaped with `|e`, only https/tg links and https logo accepted, neutral page when variables are absent). It tries `admin.custom_variables` and `custom_variables`. Melorin still never writes `sub_template` or HTML. `tests/test_sub_template.py` renders it with an escaping-off Jinja environment (worst case).
- **After:** 5 new tests pass. STILL UNVERIFIED on a live panel: under which name the panel exposes `custom_variables` to the template; the first apply on a test store must confirm it, and the template line that reads them must be adjusted if not.

## 2026-11-09 - PG-12: screens for store usage report and subscription branding (store-web, admin-web)
- **Area:** store-web / admin-web / tests
- **Before:** the usage-report API (`/reseller/usage-report`), the branding fields API (`/reseller/sub-branding`) and the admin apply/revert API existed, but no web screen used them; only the reseller bot showed the usage report.
- **Problem:** a store owner on the site could not see usage or set the subscription-page brand, and the admin had no button for the audited "apply to panel" step.
- **Action:** store-web: new tab "گزارش مصرف" (`ResellerUsage.jsx`: live summary, 5 top consumers, "temporarily unavailable" and no numbers when the panel does not answer, never IP/links) and a branding form under "ادمین پنل" (`ResellerSubBranding.jsx`: name, support link, logo; saves only changed fields, nothing is sent to a panel). admin-web: `SubBrandingCard.jsx` in the panel-admin drawer (shows wanted vs on-panel, apply/remove only after typing the panel name, disabled while the panel is unreachable). No backend change.
- **After:** 4 new store-web tests (76 total) and 3 new admin-web tests (212 total) pass; the 26 backend tests of both features pass. The panel's page template reading `melorin_*` variables is still unverified on a live panel (PasarGuard docs do not describe it).

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

### 2026-11-09 - Claude (with owner) - PG-12 per-store subscription branding
- **Before:** every store's subscription page carried the shared panel branding; `stores.branding` was free-form JSON replaced wholesale by the owner patch.
- **Problem:** a reseller could not show its own name, support link or logo; a free-form value that a panel page may print is an injection risk.
- **Action:** `modules/vpn_accounts/sub_branding.py` (validated fields in `stores.branding["sub"]`; admin `preview` / `apply` / `revert` writing three `custom_variables` keys of the store's panel admin, other keys kept, read-back verified with restore, typed panel name, audited without values); owner `GET/PUT /stores/{id}/reseller/sub-branding`; the generic branding patch can no longer set or wipe `sub`/`sub_applied`; adapter `read_custom_variables` / `write_custom_variables`; no `sub_template`, no HTML from stores.
- **After:** `tests/test_sub_branding.py` (9 tests) and the 5.6.0 contract replay pass. No migration. NOT run against a live panel; how the panel page reads `custom_variables` is unconfirmed.
- **Ref:** this commit

