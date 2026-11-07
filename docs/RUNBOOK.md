# Melorin operations runbook

## Deploy
The normal path is automatic and CI-gated; see **Release, rollback and alerting** below. The manual steps are:

1. Put production secrets in the secret manager, never `.env` in git.
2. `docker compose pull && docker compose build`.
3. Take a DB backup and run `docker compose run --rm api alembic upgrade head`.
4. `docker compose up -d`; verify `/health/live` and `/health/ready`.
5. Check worker logs and a controlled staging purchase.

## PostgreSQL failure
Stop writes at Caddy or disable the `purchase` and `payment` feature flags. Restore the latest encrypted backup to a new instance. Run migrations and integrity checks, then re-enable in staging first.

## Redis failure
The database remains the financial source of truth (orders, ledger, outbox). Redis only holds queues, rate-limit counters and the worker heartbeat.

**Customer impact while Redis is down in staging/production: nobody can sign in.** Rate limiting fails closed, so every rate-limited endpoint (e-mail code, password, refresh, Telegram/Google sign-in, order and top-up creation, ...) answers `429 RATE_LIMITED`. This is intentional: a per-process fallback would multiply each limit by the number of API workers, so an attacker could brute-force logins exactly when the platform is degraded. Sessions that already exist keep working for reads; `/health/ready` reports 503 (worker heartbeat lives in Redis) and alert `MelorinRedisUnavailable` fires.

Operating rules:
* Treat a planned Redis restart as a short login outage; do it off-peak. `docker compose up -d` in `deploy.sh` recreates Redis only when its image or config changed.
* After Redis returns, verify `/health/ready` is 200 before announcing recovery. No data repair is needed; queued work is replayed from the PostgreSQL outbox.
* There is deliberately no switch to relax this in staging/production: the config validator refuses `MELORIN_REQUIRE_REDIS_RATE_LIMIT=false` there (only development may use the per-process fallback). Keep Redis healthy instead: it is capped (`--maxmemory 160mb`, `noeviction`) and restarts automatically (`restart: unless-stopped`).

## Panel failure
Panel health becomes unhealthy; provisioning selects no server and sends orders to manual review. Do not refund until Panel state is reconciled. Use admin retry or attach an existing account.

## PasarGuard panel operations (Phase 1)

**What Melorin now watches.** `panel_health_job` (5 min) reports `healthy | degraded | unhealthy` per panel and keeps one row per node in
`panel_nodes`. `degraded` = the panel answers but a node is down (the reason is shown in Admin -> Panel operations, e.g. "self-signed
certificate"); `unhealthy` = the panel does not answer or no node can serve. A server whose destination has no healthy node is skipped
for **new** orders only; existing accounts are untouched. `reconciliation_job` (hourly) mirrors panel state onto accounts (`active`,
`suspended`, `limited`, `expired`, `on_hold`), opens at most one issue per account and kind (`missing_on_panel`, `panel_unreachable`,
`owner_mismatch`, `limits_mismatch`), closes it by itself when the condition clears, and lists panel users Melorin does not know
(`panel_orphans`) - it never deletes anything on a panel.

**Working the queue** (Admin -> Panel operations): `resync` re-checks one account now; `fix_owner` only calls `set_owner`;
`archive_account` only archives the Melorin row of a user that is really gone; `ignore` needs a reason. Unknown panel users can only be
listed or ignored.

**Alerts / metrics.** `melorin_reconcile_open_issues{kind}` (every kind is always exported), `melorin_reconcile_lag_seconds` (age of the
least recently synced live account; absent while an account was never synced) and the existing `MelorinPanelsUnhealthy` alert.

**Low-traffic warnings are per store** (Admin -> Panel operations -> "هشدار حجم", or the API): `GET/PUT/DELETE /api/v1/admin/stores/{id}/vpn-notices` (`{"traffic_low_levels": [80, 90]}`, 1-99,
at most 4, `[]` = none). A level already sent stays sent; a renewal starts a new package and resets them.

**PG-18 operating rules**
1. *One controller per panel.* If a legacy tool (for example `PGClockBot`) also writes to the same PasarGuard, either stop it or make
   it read-only before go-live; two writers fight over owner, status and deletes. Check with `systemctl status pgclockbot`.
2. *Secrets in panel settings.* A Telegram bot token stored in the panel's notification settings is readable by anyone with
   `settings` access. Revoke it in BotFather and set a new one before production; customer notices must come from Melorin only.
3. *Nodes failing with `CERTIFICATE_VERIFY_FAILED (self-signed)`.* Fix it on the panel side: put the node's CA in the node's
   `server_ca` or install a valid certificate. Never disable TLS verification in Melorin (`verify_tls=false` is refused outside
   development, correctly).
5. *Caddy shows `unhealthy` with `OCI runtime exec failed: procReady not received`.* The error happens before `wget` runs, so the
   Caddyfile and the healthcheck command are not the cause - it is the Docker/runc exec path on the host. Check
   `docker inspect --format '{{json .State.Health.Log}}' <caddy>`, then `docker version` / `runc --version` and the kernel log, restart
   the container, and if it persists update Docker. Do not silence the check: an unhealthy flag that is always on hides a real one.

## PasarGuard live events (Phase 2)

**What it does.** The panel pushes "something happened to user X" (limited, expired, enabled, disabled, deleted, usage/days thresholds,
usage reset, link revoked) to `POST /api/v1/webhooks/pasarguard/{panel_id}`. The endpoint only authenticates, stores and answers 200;
the worker (`panel_event_job`, every 10 s, plus a best-effort sweep right after each delivery) re-reads the user from the panel and
mirrors it with the same code as the hourly reconcile. **The event payload is never used as state**, so a replayed, stale, out-of-order
or forged-but-authenticated event cannot write wrong data. The hourly reconcile stays the safety net for lost events. Nothing here
writes to a panel (except the one-time connect below) and nothing deletes: `user_deleted` only opens a `missing_on_panel` issue.

**Connecting** (Admin -> Panel operations -> choose the panel -> "رویدادهای زنده" -> اتصال; or `POST /api/v1/admin/panels/{id}/events/connect`
with `{"confirm": true}`). Needs `MELORIN_PUBLIC_API_URL` (HTTPS) and a panel role with `settings.update`. Melorin generates the shared
secret, stores it encrypted, and writes exactly one panel setting: its own webhook target (it also fills usage-percent/days-left
thresholds only where the panel has none). If the panel refuses the write the previous secret is restored. The secret is never returned by
any API. `rotate_secret: true` issues a new one; `disconnect` removes only Melorin's target.

**Security model.** The panel authenticates with the `x-webhook-secret` header (no HMAC exists on the panel side), so the endpoint must be
HTTPS-only and the secret never logged. Constant-time compare; a panel that is unknown, disabled or not connected answers exactly like a
wrong secret; per-IP rate limit plus a much tighter limit on wrong secrets; body cap 512 KB, at most 500 events per delivery.

**Delivery semantics.** At-least-once. Idempotency key = the panel's event `id` (or action + username + `enqueued_at`), UNIQUE per panel.
A panel that sends neither gets a key made of the content and the minute it arrived (an immediate re-delivery is a duplicate, a new event is not).
The worker reads the panel without holding the account's row lock and repeats the read under the lock when the account changed meanwhile.
A delivery is never failed because of one bad item (`Infinity`, `NaN`, wrong types): it is counted as `rejected` and skipped.
Events are claimed with a 10-minute lease (a crashed worker's rows return to the queue), coalesced per user (ten events = one panel read),
retried with back-off (10 s, 30 s, 2 min, 10 min, then every 30 min). A panel outage, timeout or 5xx is retried up to 12 times (about
3.5 hours); a permanent panel error (auth, validation) or an internal error fails after 5 attempts. Then `failed`. Events are ignored when older than 7 days, and purged 30 days
after they finish (`panel_event_purge_job`, 03:20). An event for a user Melorin does not know yet is retried briefly (it can outrun the
commit of a brand-new account) and then ignored; reconcile lists that user as a discovered one.

**Customer notices.** A status change seen through an event goes through the same notices as reconcile (`traffic_exhausted`,
`expired`, `disabled_by_panel`, low-traffic levels per store). `reached_days_left` fires at the *panel's* thresholds; Melorin warns inside
its own `vpn.near_expiry_hours` window, once per period (the flag resets on renewal). After connecting, turn off the panel's own Telegram
notifications for customers so nobody is notified twice.

**Operating it.**
- State and counters: `GET /api/v1/admin/panels/{id}/events/status` (`?live=true` also reads the panel's own webhook settings and warns
  if Melorin was removed from the panel or the webhook is off there). List: `GET .../events?status=&action=&username=&limit=&offset=`.
- `POST .../events/process` runs one sweep now; `POST .../events/retry-failed` re-queues `failed` events (all, or `?event_id=`).
- Metrics: `melorin_panel_events_total{action,status}`, `melorin_panel_events_pending`, `melorin_panel_webhook_lag_seconds{panel}`,
  `melorin_panel_webhook_rejected_total{reason}`. Alert `MelorinPanelWebhookSilent`: a connected panel that has users has sent nothing
  for 6 h (it may simply be quiet; check "بررسی تنظیمات پنل" first - someone may have cleared the webhook in the panel).
- Many `failed` events: look at `outcome` in the list; usually the panel was unreachable (fix, then retry-failed). Rejections rising:
  a wrong secret (rotate and reconnect) or a scanner (rate limits already apply).

## Gateway / callback incident
Payment callback is idempotent. Inspect `payment_attempts`, never manually edit payment status without audit and ledger compensation.

## Card-to-card auto verification (bank SMS)
Design and setup: `docs/20-Card-Receipt-Auto-Verification.md`. If receipts stop being paid automatically: check the store's
`last_received_at` (phone/forwarder offline?), `GET /admin/stores/{id}/bank-sms?status=unparsed|ambiguous`, a *balance gap*
flag (a missed SMS), then run "بررسی دوباره" (`POST .../bank-sms/reconcile`). Turn "شارژ خودکار" off to fall back to
suggest-only; never edit a payment by hand without audit and ledger compensation. Rotate the webhook token if it leaks.

## Data corruption
Disable affected feature, preserve DB and audit logs, export evidence, restore to isolated DB, run reconciliation and migration tests. Never delete ledger/audit rows.

## Backup policy
Default is 1 run/day, 30-day retention, encrypted local plus off-server copy. A backup is not considered valid until a scheduled restore test passes.

## v1.1 release checks

1. Set non-development JWT, encryption, bot and database secrets. Never use the checked-in defaults.
2. Configure each PasarGuard panel with `group_ids`, verify TLS, and run the Admin panel health check. Use a restricted PasarGuard credential that can create/modify/read users only.
3. Configure a payment destination for every Store. A reseller Store must never inherit the Main Store destination.
4. Run `alembic upgrade head`, then exercise wallet top-up, duplicate callback, wallet-only checkout, coupon quota concurrency, reseller debt-limit boundary, refund/clawback and webhook retry tests.
5. Verify ARQ/Redis queue health and PostgreSQL outbox recovery after a worker restart.
6. Perform a real restore drill and record RPO <= 24h and RTO <= 8h before enabling production sales.


## Acceptance smoke

Run `MELORIN_RUN_EXTERNAL_PROVIDERS=1 scripts/integration_smoke.sh` with a real panel URL and sandbox payment credentials before selling. Run `MELORIN_RUN_TELEGRAM_SMOKE=1 scripts/integration_smoke.sh` with a rotated BotFather token to verify Telegram. Record the results with `scripts/ops_log.sh`; do not paste secrets into ClickUp, logs, or reports.


## Session and backup acceptance

For a live deployment, run `BASE_URL=https://shop.example.com COOKIE_JAR=... python scripts/auth_cookie_smoke.py` to verify refresh-cookie rotation, HttpOnly protection, and same-origin CORS behavior. Run `scripts/backup_restore_verify.sh` for archive verification and `scripts/backup_restore_drill.sh` against an isolated PostgreSQL 16 database for a real restore drill.

## Reseller store domains (Caddy)

A reseller's domain is served by the bundled Caddy as soon as the store exists: the reseller points an `A`/`AAAA` record at this server, and on the first HTTPS visit Caddy asks Core (`GET /api/v1/tls/ask?domain=<host>`) whether the name is an active reseller store domain; only then does it request a certificate (on-demand TLS). Unknown names get no certificate. The domain shows the reseller's storefront (the web app resolves the store from the hostname via `/api/v1/stores/by-domain/<host>`), never the admin panel.

Checks: `docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile`; from inside the network `curl -s -o /dev/null -w '%{http_code}' 'http://api:8000/api/v1/tls/ask?domain=shop.example.com'` (200 registered, 404 otherwise). If a certificate does not appear, check DNS first, then the Caddy log for the ACME error (rate limits, port 80/443 reachability). With `EXTERNAL_PROXY=true` the bundled Caddy is off: route reseller domains to the store port in the host proxy and gate on-demand certificates with the same ask URL.

## Release, rollback and alerting (audit P0)

**Deploys are gated by CI.** `deploy.yml` runs only after a *successful* `CI` run on a push to `main` (`workflow_run`) and deploys exactly the commit CI tested. A manual run (`workflow_dispatch`) re-checks that the ref is on `main` and has a green CI run (a commit that differs from a CI-green ancestor only by the Changelog bot's `docs/CHANGE_LOG.md` entries is accepted, because bot pushes never start CI). It streams that commit's `scripts/deploy.sh` to the server, which: takes a lock, refuses hand-edited tracked files, takes an encrypted pre-deploy backup through the worker (aborts if it fails), builds, runs `alembic upgrade head`, starts the stack and waits for `/health/ready` (DB + Redis + worker) and healthy core services. Any failure after the checkout **automatically restores the previous commit**, rebuilds and re-verifies; the exit code is 1 (rolled back) or 2 (rollback failed - intervene). Bots that are unhealthy only produce a warning.

* Manual deploy/rollback on the server: `cd /opt/melorin && scripts/deploy.sh --ref <sha-or-tag>`. Rolling *back* to an older release is the same command with the older ref.
* Rollback restores **code**. The schema stays at the new revision (migrations 0002/0011/0023/0026 have no-op downgrades). Pass `--db-downgrade` to also run `alembic downgrade` to the previous revision when you know the downgrades are real. The pre-deploy backup path is printed on every failure; restore data by hand only if a migration was destructive.
* `scripts/test_deploy.sh` (CI + `make deploy-test`) proves success, health/migration rollback, backup abort, dirty-tree refusal and streaming via `bash -s` with a fake `docker`; `scripts/test_restore_drill.sh` covers the restore-drill wrapper.
* Branch protection is a separate, optional step (`scripts/enable_branch_protection.sh`, needs repo admin; read the caveat about the changelog bot in the script header).

**Restart after crash or reboot.** Every compose service has `restart: unless-stopped`. This also needs the Docker daemon to start at boot: `systemctl enable --now docker`.

**Alerts are delivered by Alertmanager.** Set at least one receiver in `.env` - Telegram (`ALERT_TELEGRAM_BOT_TOKEN`, `ALERT_TELEGRAM_CHAT_ID`) and/or e-mail (`ALERT_SMTP_HOST` as `host:port`, `ALERT_SMTP_FROM`, `ALERT_EMAIL_TO`, optional `ALERT_SMTP_USER`/`ALERT_SMTP_PASSWORD`) - then `docker compose up -d alertmanager prometheus`. Without a receiver the stack still boots but `deploy.sh` warns on every deploy and Alertmanager logs a warning. Test delivery: `docker compose exec alertmanager wget -qO- --post-data='[{"labels":{"alertname":"TestAlert","severity":"warning"}}]' --header='Content-Type: application/json' http://127.0.0.1:9093/api/v2/alerts`.

**Prove restores (T4/T5).** Store the age *identity* (private key) **off the server** (password manager + one offline copy); the server only needs the recipients file. `scripts/restore_drill_latest.sh` restores the newest backup (directory or `rclone` remote) into a scratch PostgreSQL, fails if the newest backup is older than `MELORIN_RPO_HOURS`, and logs the result to `var/restore-drill.log`. `restore-drill.yml` runs it weekly on GitHub with the secrets `BACKUP_OFFSITE_URI`, `RCLONE_CONFIG` and `BACKUP_AGE_IDENTITY`; without them it is skipped. Do one manual drill before real traffic and record the date with `scripts/ops_log.sh`.

## Memory budget and capacity (audit W6)

Every container has a `mem_limit` in `docker-compose.yml`, and the caps add up to **3584 MiB (3.5 GiB)**, which is why the README recommends **4 GB RAM**. The caps are ceilings, not reservations: typical use is far below them, but the host must be able to honour them. `scripts/check_ops_p0.py` (CI, `make guards`) fails when a service has no cap or the sum passes `MEMORY_BUDGET_MIB`; raise the README recommendation together with that constant.

| Service | Cap | | Service | Cap |
|---|---|---|---|---|
| postgres | 768 MiB | | store_web / admin_web | 64 MiB each |
| api / worker | 768 MiB each | | telegram_main | 192 MiB |
| redis | 256 MiB (`--maxmemory 160mb`, `noeviction`) | | telegram_reseller | 256 MiB |
| prometheus | 256 MiB | | caddy / alertmanager | 128 / 64 MiB |

* Redis stops itself at 160 MB instead of being OOM-killed. With `noeviction` it never drops a queued job or a rate-limit counter silently: writes fail, rate limiting fails closed (see *Redis failure*) and the PostgreSQL outbox stays the source of truth. Alert `MelorinRedisUnavailable` fires.
* A container that hits its cap is killed and restarted by `restart: unless-stopped`; look for `OOMKilled` in `docker inspect`. If one service keeps hitting its cap, raise that cap **and** the budget, or move the host to the next size.
* `deploy.sh` builds with `COMPOSE_PARALLEL_LIMIT=2` while the old stack still serves, so a 4 GB host keeps headroom during a deploy.

## Reproducible builds and supply chain (audit W17)

* **Python dependencies are hash-locked.** Edit `apps/api/requirements.in` (runtime) or `requirements-dev.in` (tests, lint), then run `scripts/lock_requirements.sh` (needs `uv`) and commit the regenerated `requirements*.txt`. Images install them with `pip install --require-hashes`, and the API image never contains test tooling. CI fails when a `.in` file and its lock disagree (`scripts/lock_requirements.sh --check`). Dependabot opens the upgrade PRs.
* **The API image is multi-stage**: the PostgreSQL signing key is fetched in a throw-away stage, so `curl`/`gnupg` are not in the image that runs.
* **Base images are pinned by digest** (`name:tag@sha256:...`). Digests come from the registries, so run the **Pin images** workflow (Actions tab, *Run workflow*) once: it opens a pull request and starts CI for it. Run it again with *refresh* to move every pin to the tags' current digests; Dependabot does the same one image at a time. Until the first run `scripts/check_ops_p0.py` only warns; once any image is pinned it requires all of them to be.
* Check locally: `python3 scripts/pin_images.py` (list), `python3 scripts/pin_images.py --check` (fail if unpinned).


## Build in CI, pull on the host (registry mode)
By default `scripts/deploy.sh` builds the images on the production host (two at a time, `COMPOSE_PARALLEL_LIMIT=2`). To stop building on production:

1. In GitHub: *Settings -> Secrets and variables -> Actions -> Variables*: add `DEPLOY_IMAGE_REGISTRY` = `ghcr.io/<owner>/melorin` (lower-case owner). The `Deploy` workflow then runs an `images` job after CI is green: it builds the five images once, tags them with the full commit sha and pushes them. A failed image build blocks the deploy.
2. On the server add `MELORIN_IMAGE_REGISTRY=ghcr.io/<owner>/melorin` to `.env`.
3. From then on `deploy.sh` pulls `<registry>/<name>:<sha>` for the exact commit and records `MELORIN_IMAGE_TAG=<sha>` in `.env` (a later plain `docker compose up -d` uses the same images). The workflow logs the server in to the registry with the run's own short-lived token; no long-lived registry credential is stored.
4. Fallbacks: if a pull fails (image missing, no login) the deploy builds on the host instead and says so; a rollback re-points the tag at the previous commit (pulled, or rebuilt if it is not available). `melorin update` (manual) resets the tag to `local` and builds on the host.

Packages pushed by a workflow are private by default; keep them private. To go back to host builds, remove `MELORIN_IMAGE_REGISTRY` from `.env`.
