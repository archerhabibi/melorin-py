# عملیات، استقرار و DR / Operations, Deployment & DR

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** نصب، اجرا، استقرار، پایش و بازیابی.



## English section

**Purpose:** Install, run, deploy, monitor and recover.



## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `18-OPERATIONS-DEPLOYMENT-DR.md`

#### استقرار، مانیتورینگ و بازیابی
##### محیط‌ها و استقرار
Development، Staging، Production جدا. Production ابتدا روی VPS ممکن است. Ubuntu LTS، Docker Compose، شبکه خصوصی برای DB/Redis، CI/CD و migration checks. Zero-downtime در V1 الزامی نیست؛ چند Instance آینده باید ممکن باشد.
##### Health
Liveness یعنی process زنده؛ Readiness یعنی آماده دریافت ترافیک؛ Dependency Health وضعیت PostgreSQL، Redis، worker، Panel و Gateway. خرابی Panel نباید بی‌دلیل کل Core را unready کند.
##### Observability
Structured logs، CPU/RAM، API latency/error rate، ARQ/Redis queue depth/age، DB pool، Panel health و شاخص‌های مالی/عملیاتی. Correlation ID از Request تا Payment/Order/Provisioning/Notification. Prometheus/Grafana و Sentry گزینه‌های پیشنهادی قابل تعویض. Secret و داده شخصی در log ماسک شود. Alert دارای threshold، deduplication، retry و recovery notification.
##### Backup
یک تا دو بار روزانه قابل تنظیم؛ Retention پیش‌فرض 30 روز. نسخه محلی و خارج از سرور، encryption-at-rest، Restore Test دوره‌ای. Telegram فقط وضعیت Backup را اعلام کند، نه فایل Backup.
##### Recovery
Runbook برای خرابی VPS، PostgreSQL، Redis، Panel، Gateway، deploy و data corruption. هدف بازیابی مصوب: RPO حداکثر 24 ساعت و RTO حداکثر 8 ساعت. این اهداف باید با زمان‌بندی Backup، آزمون Restore و تمرین دوره‌ای سنجیده شوند؛ Backup بدون Restore Test کافی نیست.
##### Emergency & Maintenance
Admin بتواند خرید، پرداخت، Reseller، Product، Panel، API، Bot و Provisioning را متوقف کند. Maintenance در سطح سیستم، Channel، Store یا Feature. همه تغییرات Audit شوند.
##### Storage/Retention
Storage abstraction برای Local یا S3-compatible. فایل Ticket/Receipt خصوصی و فقط از مسیر Authorization قابل دسترسی. Cleanup نباید سوابق مالی/Audit را حذف کند.

##### M7.6 — Alerts and metrics

`/metrics` (bearer token) now exposes, besides the existing counters: `melorin_http_request_duration_seconds` (histogram, bounded `path` label), and database-derived gauges refreshed on every scrape: `melorin_payments_recent_{total,failed,failure_ratio}` (15 min), `melorin_orders_provisioning_failed_recent` (1 h), `melorin_orders_needs_review`, `melorin_reseller_bots_unhealthy`, `melorin_backup_age_seconds`.

| Alert | Fires when |
|---|---|
| MelorinHttpErrorRateHigh | 5xx ratio > 5% for 5 min |
| MelorinHttpLatencyHigh | p95 latency > 2.5 s for 10 min |
| MelorinPaymentFailureRateHigh | > 50% of ≥ 5 recent payments failed |
| MelorinProvisioningFailures | any order failed provisioning in the last hour |
| MelorinResellerBotUnhealthy | a reseller bot is offline (stale heartbeat) or in error |
| MelorinBackupStale | no successful backup for 36 h (or ever) |

`tests/test_observability_metrics.py` checks that every alert expression only references metrics the code really emits.

##### Backup implementation

Backup source is implemented by `scripts/backup_secure.sh`. It uses `PGPASSFILE`, age recipient encryption, SHA-256 verification, retention cleanup, and optional rclone off-host copy. Restore evidence is checked by `scripts/backup_restore_verify.sh`, which verifies the checksum, decrypts the archive, and runs `pg_restore --list`.

These scripts are integration boundaries, not proof of a completed production restore. A release still requires PostgreSQL, age, off-host storage, and a real restore drill.

### منبع / Source: `18-OPERATIONS-DEPLOYMENT-DR.md`

#### Melorin operations runbook

##### Deploy
The normal path is automatic and CI-gated; see **Release, rollback and alerting** below. The manual steps are:

1. Put production secrets in the secret manager, never `.env` in git.
2. `docker compose pull && docker compose build`.
3. Take a DB backup and run `docker compose run --rm api alembic upgrade head`.
4. `docker compose up -d`; verify `/health/live` and `/health/ready`.
5. Check worker logs and a controlled staging purchase.

##### PostgreSQL failure
Stop writes at Caddy or disable the `purchase` and `payment` feature flags. Restore the latest encrypted backup to a new instance. Run migrations and integrity checks, then re-enable in staging first.

##### Redis failure
The database remains the financial source of truth (orders, ledger, outbox). Redis only holds queues, rate-limit counters and the worker heartbeat.

**Customer impact while Redis is down in staging/production: nobody can sign in.** Rate limiting fails closed, so every rate-limited endpoint (e-mail code, password, refresh, Telegram/Google sign-in, order and top-up creation, ...) answers `429 RATE_LIMITED`. This is intentional: a per-process fallback would multiply each limit by the number of API workers, so an attacker could brute-force logins exactly when the platform is degraded. Sessions that already exist keep working for reads; `/health/ready` reports 503 (worker heartbeat lives in Redis) and alert `MelorinRedisUnavailable` fires.

Operating rules:
* Treat a planned Redis restart as a short login outage; do it off-peak. `docker compose up -d` in `deploy.sh` recreates Redis only when its image or config changed.
* After Redis returns, verify `/health/ready` is 200 before announcing recovery. No data repair is needed; queued work is replayed from the PostgreSQL outbox.
* There is deliberately no switch to relax this in staging/production: the config validator refuses `MELORIN_REQUIRE_REDIS_RATE_LIMIT=false` there (only development may use the per-process fallback). Keep Redis healthy instead: it is capped (`--maxmemory 160mb`, `noeviction`) and restarts automatically (`restart: unless-stopped`).

##### Panel failure
Panel health becomes unhealthy; provisioning selects no server and sends orders to manual review. Do not refund until Panel state is reconciled. Use admin retry or attach an existing account.

##### PasarGuard panel operations (Phase 1)

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

##### PasarGuard live events (Phase 2)

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

##### Gateway / callback incident
Payment callback is idempotent. Inspect `payment_attempts`, never manually edit payment status without audit and ledger compensation.

##### Card-to-card auto verification (bank SMS)
Design and setup: `docs/15-PAYMENTS-WALLET-FINANCE.md`. If receipts stop being paid automatically: check the store's
`last_received_at` (phone/forwarder offline?), `GET /admin/stores/{id}/bank-sms?status=unparsed|ambiguous`, a *balance gap*
flag (a missed SMS), then run "بررسی دوباره" (`POST .../bank-sms/reconcile`). Turn "شارژ خودکار" off to fall back to
suggest-only; never edit a payment by hand without audit and ledger compensation. Rotate the webhook token if it leaks.

##### Data corruption
Disable affected feature, preserve DB and audit logs, export evidence, restore to isolated DB, run reconciliation and migration tests. Never delete ledger/audit rows.

##### Backup policy
Default is 1 run/day, 30-day retention, encrypted local plus off-server copy. A backup is not considered valid until a scheduled restore test passes.

##### v1.1 release checks

1. Set non-development JWT, encryption, bot and database secrets. Never use the checked-in defaults.
2. Configure each PasarGuard panel with `group_ids`, verify TLS, and run the Admin panel health check. Use a restricted PasarGuard credential that can create/modify/read users only.
3. Configure a payment destination for every Store. A reseller Store must never inherit the Main Store destination.
4. Run `alembic upgrade head`, then exercise wallet top-up, duplicate callback, wallet-only checkout, coupon quota concurrency, reseller debt-limit boundary, refund/clawback and webhook retry tests.
5. Verify ARQ/Redis queue health and PostgreSQL outbox recovery after a worker restart.
6. Perform a real restore drill and record RPO <= 24h and RTO <= 8h before enabling production sales.


##### Acceptance smoke

Run `MELORIN_RUN_EXTERNAL_PROVIDERS=1 scripts/integration_smoke.sh` with a real panel URL and sandbox payment credentials before selling. Run `MELORIN_RUN_TELEGRAM_SMOKE=1 scripts/integration_smoke.sh` with a rotated BotFather token to verify Telegram. Record the results with `scripts/ops_log.sh`; do not paste secrets into ClickUp, logs, or reports.


##### Session and backup acceptance

For a live deployment, run `BASE_URL=https://shop.example.com COOKIE_JAR=... python scripts/auth_cookie_smoke.py` to verify refresh-cookie rotation, HttpOnly protection, and same-origin CORS behavior. Run `scripts/backup_restore_verify.sh` for archive verification and `scripts/backup_restore_drill.sh` against an isolated PostgreSQL 16 database for a real restore drill.

##### Reseller store domains (Caddy)

A reseller's domain is served by the bundled Caddy as soon as the store exists: the reseller points an `A`/`AAAA` record at this server, and on the first HTTPS visit Caddy asks Core (`GET /api/v1/tls/ask?domain=<host>`) whether the name is an active reseller store domain; only then does it request a certificate (on-demand TLS). Unknown names get no certificate. The domain shows the reseller's storefront (the web app resolves the store from the hostname via `/api/v1/stores/by-domain/<host>`), never the admin panel.

Checks: `docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile`; from inside the network `curl -s -o /dev/null -w '%{http_code}' 'http://api:8000/api/v1/tls/ask?domain=shop.example.com'` (200 registered, 404 otherwise). If a certificate does not appear, check DNS first, then the Caddy log for the ACME error (rate limits, port 80/443 reachability). With `EXTERNAL_PROXY=true` the bundled Caddy is off: route reseller domains to the store port in the host proxy and gate on-demand certificates with the same ask URL.

##### Release, rollback and alerting (audit P0)

**Deploys are gated by CI.** `deploy.yml` runs only after a *successful* `CI` run on a push to `main` (`workflow_run`) and deploys exactly the commit CI tested. A manual run (`workflow_dispatch`) re-checks that the ref is on `main` and has a green CI run (a commit that differs from a CI-green ancestor only by the Changelog bot's `docs/06-ARCHITECTURE-DECISIONS.md` entries is accepted, because bot pushes never start CI). It streams that commit's `scripts/deploy.sh` to the server, which: takes a lock, refuses hand-edited tracked files, takes an encrypted pre-deploy backup through the backup container (aborts if it fails), builds, runs `alembic upgrade head`, starts the stack and waits for `/health/ready` (DB + Redis + worker) and healthy core services. Any failure after the checkout **automatically restores the previous commit**, rebuilds and re-verifies; the exit code is 1 (rolled back) or 2 (rollback failed - intervene). Bots that are unhealthy only produce a warning.

* Manual deploy/rollback on the server: `cd /opt/melorin && scripts/deploy.sh --ref <sha-or-tag>`. Rolling *back* to an older release is the same command with the older ref.
* Rollback restores **code**. The schema stays at the new revision (migrations 0002/0011/0023/0026 have no-op downgrades). Pass `--db-downgrade` to also run `alembic downgrade` to the previous revision when you know the downgrades are real. The pre-deploy backup path is printed on every failure; restore data by hand only if a migration was destructive.
* `scripts/test_deploy.sh` (CI + `make deploy-test`) proves success, health/migration rollback, backup abort, dirty-tree refusal and streaming via `bash -s` with a fake `docker`; `scripts/test_restore_drill.sh` covers the restore-drill wrapper.
* Branch protection is a separate, optional step (`scripts/enable_branch_protection.sh`, needs repo admin; read the caveat about the changelog bot in the script header).

**Restart after crash or reboot.** Every compose service has `restart: unless-stopped`. This also needs the Docker daemon to start at boot: `systemctl enable --now docker`.

**Alerts are delivered by Alertmanager.** Set at least one receiver in `.env` - Telegram (`ALERT_TELEGRAM_BOT_TOKEN`, `ALERT_TELEGRAM_CHAT_ID`) and/or e-mail (`ALERT_SMTP_HOST` as `host:port`, `ALERT_SMTP_FROM`, `ALERT_EMAIL_TO`, optional `ALERT_SMTP_USER`/`ALERT_SMTP_PASSWORD`) - then `docker compose up -d alertmanager prometheus`. Without a receiver the stack still boots but `deploy.sh` warns on every deploy and Alertmanager logs a warning. Test delivery: `docker compose exec alertmanager wget -qO- --post-data='[{"labels":{"alertname":"TestAlert","severity":"warning"}}]' --header='Content-Type: application/json' http://127.0.0.1:9093/api/v2/alerts`.

**Prove restores (T4/T5).** Store the age *identity* (private key) **off the server** (password manager + one offline copy); the server only needs the recipients file. `scripts/restore_drill_latest.sh` restores the newest backup (directory or `rclone` remote) into a scratch PostgreSQL, fails if the newest backup is older than `MELORIN_RPO_HOURS`, and logs the result to `var/restore-drill.log`. `restore-drill.yml` runs it weekly on GitHub with the secrets `BACKUP_OFFSITE_URI`, `RCLONE_CONFIG` and `BACKUP_AGE_IDENTITY`; without them it is skipped. Do one manual drill before real traffic and record the date with `scripts/ops_log.sh`.

##### Memory budget and capacity (audit W6)

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

##### Reproducible builds and supply chain (audit W17)

* **Python dependencies are hash-locked.** Edit `apps/api/requirements.in` (runtime) or `requirements-dev.in` (tests, lint), then run `scripts/lock_requirements.sh` (needs `uv`) and commit the regenerated `requirements*.txt`. Images install them with `pip install --require-hashes`, and the API image never contains test tooling. CI fails when a `.in` file and its lock disagree (`scripts/lock_requirements.sh --check`). Dependabot opens the upgrade PRs.
* **The API image is multi-stage**: the PostgreSQL signing key is fetched in a throw-away stage, so `curl`/`gnupg` are not in the image that runs.
* **Base images are pinned by digest** (`name:tag@sha256:...`). Digests come from the registries, so run the **Pin images** workflow (Actions tab, *Run workflow*) once: it opens a pull request and starts CI for it. Run it again with *refresh* to move every pin to the tags' current digests; Dependabot does the same one image at a time. Until the first run `scripts/check_ops_p0.py` only warns; once any image is pinned it requires all of them to be.
* Check locally: `python3 scripts/pin_images.py` (list), `python3 scripts/pin_images.py --check` (fail if unpinned).


##### Build in CI, pull on the host (registry mode)
By default `scripts/deploy.sh` builds the images on the production host (two at a time, `COMPOSE_PARALLEL_LIMIT=2`). To stop building on production:

1. In GitHub: *Settings -> Secrets and variables -> Actions -> Variables*: add `DEPLOY_IMAGE_REGISTRY` = `ghcr.io/<owner>/melorin` (lower-case owner). The `Deploy` workflow then runs an `images` job after CI is green: it builds the five images once, tags them with the full commit sha and pushes them. A failed image build blocks the deploy.
2. On the server add `MELORIN_IMAGE_REGISTRY=ghcr.io/<owner>/melorin` to `.env`.
3. From then on `deploy.sh` pulls `<registry>/<name>:<sha>` for the exact commit and records `MELORIN_IMAGE_TAG=<sha>` in `.env` (a later plain `docker compose up -d` uses the same images). The workflow logs the server in to the registry with the run's own short-lived token; no long-lived registry credential is stored.
4. Fallbacks: if a pull fails (image missing, no login) the deploy builds on the host instead and says so; a rollback re-points the tag at the previous commit (pulled, or rebuilt if it is not available). `melorin update` (manual) resets the tag to `local` and builds on the host.

Packages pushed by a workflow are private by default; keep them private. To go back to host builds, remove `MELORIN_IMAGE_REGISTRY` from `.env`.


##### PasarGuard operations (Phase 4)
Node errors, outage compensation, bulk disable/enable and store suspension policy are described in `docs/17-INTEGRATIONS-PROVIDERS.md`.

##### Panel lost: how Melorin converges (PasarGuard Phase 5, PG-16)
Use this when the PasarGuard panel (not Melorin) is gone, reinstalled or restored from an old copy.

1. **Stop the damage.** In Admin -> Panels -> "عملیات" pause selling on the affected server (disable the server or its products). Existing customers keep their data in Melorin.
2. **Restore the panel.** Take the newest `panel-*.tar.age` from the backup directory (or the S3 copy), decrypt it with the age identity kept OFF the server, then
   `tar -xf` it and restore `panel-db.dump` with `pg_restore --clean --if-exists --no-owner -d <panel database>` using the panel database's own port, and unpack `panel-data.tar` over the panel's data directory.
   Start the panel and open it once to confirm users, nodes and the owner admin exist.
3. **Check the connection.** Panels -> test connection; the credential Melorin uses (API key or service admin, PG-05) may have to be re-created if the restore predates it.
4. **Let reconcile converge.** Run "بررسی مجدد" or wait for the hourly reconcile: accounts created after the backup show as `missing_on_panel` issues (use "re-create on panel"
   or archive); users that exist only on the panel show up under "کاربران ناشناس" (import or ignore, never auto-deleted). Store admins are rebuilt by `panel_admin_sync_job` within 15 minutes (or at once with "sync now").
5. **Verify settings.** Open the "شاخص و پشتیبان" tab and press "بررسی اکنون": fix webhook, subscription prefix and auto-delete drift on the panel side (Melorin writes no setting without your confirmation). Reconnect live events if needed.
6. **Prove the backup next time.** Run `BACKUP_ARCHIVE=... BACKUP_IDENTITY_FILE=... scripts/verify_panel_backup.sh` (non-destructive) after any change and at least monthly. The host's `pg_restore` must be at least as new as the panel's PostgreSQL (the panel runs 17, Ubuntu 24.04 has 16): then add `PG_RESTORE='docker exec -i pasarguard-timescaledb-1 pg_restore'` (a pasted-in command reads the dump from stdin).
7. **Re-enable selling** once nodes are `connected` and the capacity/health view is green, then confirm a fresh panel backup runs the next day (`melorin_backup_age_seconds{target="panel"}`).

If the backup is stale or not configured, the admin tab says so and alert `MelorinPanelBackupStale` fires. See `docs/17-INTEGRATIONS-PROVIDERS.md`.

### منبع / Source: `18-OPERATIONS-DEPLOYMENT-DR.md`

#### Install audit / گزارش ممیزی نصب (2026-11-11)

Server: Ubuntu 22.04, 2 vCPU, 4 GB RAM, Hetzner. Domains: shop.88promax.ir, admin.88promax.ir. One-liner from the README, followed by the menu's unattended install path.

##### English

###### 1. Errors found while installing (fixed on `fix/install-hardening`)
| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | `alertmanager` crash-looped (`can't open /etc/alertmanager/entrypoint.sh: Permission denied`); the whole stack stayed down because Prometheus, API-dependent services and Caddy wait on it | The host shell had `umask 077`, so `git clone` produced 0600/0700 files. Containers that run as `nobody` (alertmanager, prometheus) cannot read bind-mounted config | `umask 022` at the top of `get.sh` and `scripts/install_server.sh` (secrets are chmod-ed explicitly anyway) |
| 2 | `melorin-caddy` stayed `unhealthy` although both sites worked | Healthcheck `wget http://127.0.0.1/health/live` was caught by the catch-all `http://` redirect and sent to `https://127.0.0.1` (no certificate) | Loopback-only exception in `infra/Caddyfile` that proxies `/health/live` to the API; everything else still redirects |

The installer is idempotent: after the fix, re-running it finished cleanly. Result: 12/12 containers healthy, both domains return HTTP 200 with valid TLS, bot token verified.

###### 2. What to collect during install, what to do after (branch `feat/post-install-hardening`)
Already collected today (5 inputs): store domain, admin domain, admin e-mail, bot token, admin Telegram ID. Keep it at five; more questions hurt the one-line experience.

Suggested improvements, implemented in `scripts/post_install.sh` (runs at the end of the installer, never fatal, opt-out `POST_INSTALL=0`, re-runnable):
1. **Credentials file** `/root/melorin-credentials.txt` (mode 600): the one-time password is removed from `.env` after bootstrap, so a scrolled terminal loses it. Delete after first login.
2. **Swap 2 GiB**: container caps add up to 3.5 GiB on a 4 GB host; swap turns an OOM kill into a slow moment.
3. **Firewall (ufw)**: SSH port is detected and allowed first, then 80/443.
4. **fail2ban** (default sshd jail).
5. **Verification report**: both HTTPS endpoints, Telegram token (`getMe`), container health, and a reminder to copy the backup age key off the server.
6. `secrets/metrics-token` kept out of `git status` (updates and drift checks stay quiet).

Suggested next, not done automatically (needs your decision): SSH key-only login and `PermitRootLogin prohibit-password`; off-site backup target (S3/rclone) in Admin; SMTP for e-mail login codes; first payment method, VPN panel (Sanaei/PasarGuard) and Zarinpal in Admin after install; Google/OIDC login if wanted; a release tag `v0.1.0` so installs stop tracking moving `main` (get.sh already warns about it); unattended-upgrades is already active on this host.

###### 3. After install (today's server)
Open https://admin.88promax.ir, log in with archerhabibi@gmail.com and the one-time password from `/root/melorin-credentials.txt`, add the TOTP seed to an authenticator, change the password, delete the file. Open the bot once and press Start so admin alerts reach Telegram ID 1992426945. Copy `/opt/melorin/secrets/backup/age-identity.txt` off the server.

##### فارسی

###### ۱. خطاهای نصب و رفع آن‌ها (برنچ `fix/install-hardening`)
| # | علامت | علت ریشه‌ای | رفع |
|---|---|---|---|
| ۱ | کانتینر `alertmanager` مدام کرش می‌کرد (`Permission denied` روی entrypoint.sh) و کل سرویس‌ها بالا نمی‌آمدند، چون Prometheus، API و Caddy منتظر آن هستند | شل سرور `umask 077` داشت و فایل‌های clone با دسترسی 0600/0700 ساخته شدند؛ کانتینرهایی که با کاربر `nobody` اجرا می‌شوند (alertmanager و prometheus) نمی‌توانند فایل‌های mount شده را بخوانند | افزودن `umask 022` به ابتدای `get.sh` و `scripts/install_server.sh` (فایل‌های حساس به‌صورت جداگانه chmod می‌شوند) |
| ۲ | کانتینر caddy با وجود کار کردن سایت‌ها «unhealthy» می‌ماند | healthcheck یعنی `wget http://127.0.0.1/health/live` توسط ریدایرکت عمومی `http://` به `https://127.0.0.1` هدایت می‌شد که گواهی ندارد | استثنای فقط-loopback در `infra/Caddyfile` که `/health/live` را به API می‌فرستد؛ بقیه مسیرها همچنان ریدایرکت می‌شوند |

نصب‌کننده idempotent است؛ بعد از رفع، اجرای مجدد تمیز تمام شد. نتیجه: ۱۲ کانتینر سالم، هر دو دامنه با HTTP 200 و TLS معتبر، توکن ربات تأیید شد.

###### ۲. چه چیزهایی هنگام نصب گرفته شود و بعد از نصب چه شود (برنچ `feat/post-install-hardening`)
اکنون پنج ورودی گرفته می‌شود: دامنه فروشگاه، دامنه ادمین، ایمیل ادمین، توکن ربات، آیدی عددی تلگرام ادمین. به نظرم همین پنج تا بماند تا تجربه تک‌خطی خراب نشود.

بهبودهای پیاده‌سازی‌شده در `scripts/post_install.sh` (انتهای نصب اجرا می‌شود، هرگز نصب را خراب نمی‌کند، با `POST_INSTALL=0` غیرفعال می‌شود و قابل اجرای مجدد است):
۱. **فایل اعتبارنامه** `/root/melorin-credentials.txt` با دسترسی 600: رمز یک‌بارمصرف بعد از bootstrap از `.env` حذف می‌شود و اگر ترمینال اسکرول شود از دست می‌رود. بعد از اولین ورود حذفش کنید.
۲. **Swap دو گیگابایتی**: سقف حافظه کانتینرها روی سرور ۴ گیگ حدود ۳٫۵ گیگ است.
۳. **فایروال ufw**: پورت SSH شناسایی و اول باز می‌شود، سپس 80 و 443.
۴. **fail2ban** با jail پیش‌فرض sshd.
۵. **گزارش راستی‌آزمایی**: هر دو آدرس HTTPS، توکن تلگرام، سلامت کانتینرها و یادآوری انتقال کلید بکاپ به بیرون از سرور.
۶. فایل `secrets/metrics-token` از `git status` کنار گذاشته می‌شود.

پیشنهادهای بعدی که تصمیمش با شماست: ورود SSH فقط با کلید و `PermitRootLogin prohibit-password`؛ مقصد بکاپ بیرونی (S3/rclone)؛ SMTP برای کد ایمیلی ورود؛ افزودن پنل VPN (سنایی/پاسارگارد)، روش پرداخت و زرین‌پال در پنل ادمین؛ ورود گوگل/OIDC در صورت نیاز؛ ساخت تگ `v0.1.0` تا نصب‌ها از `main` متحرک استفاده نکنند.

###### ۳. بعد از نصب (همین سرور)
وارد https://admin.88promax.ir شوید، با archerhabibi@gmail.com و رمز موجود در `/root/melorin-credentials.txt` لاگین کنید، seed کد TOTP را در برنامه احراز هویت اضافه کنید، رمز را عوض و فایل را حذف کنید. یک بار ربات را باز و Start بزنید تا هشدارها به آیدی 1992426945 برسد. فایل `/opt/melorin/secrets/backup/age-identity.txt` را حتماً بیرون از سرور نگه دارید.

### منبع / Source: `18-OPERATIONS-DEPLOYMENT-DR.md`

<div dir="rtl" lang="fa">

#### T05 — گزارش نصب ملورین روی سرور تمیز (فارسی)

تاریخ: ۱۱ نوامبر ۲۰۲۶ · سرور: Ubuntu 22.04، ۲ vCPU، ۴ گیگ RAM، ۴۰ گیگ دیسک (Hetzner) · دامنه‌ها: `shop.88promax.ir` (فروشگاه) و `admin.88promax.ir` (ادمین)
نسخهٔ نصب‌شده: شاخهٔ `main` (commit `d7be664`؛ هنوز هیچ تگ release وجود ندارد).

##### ۱. خلاصه
- نصب با همان دستور تک‌خطی README انجام شد و **بدون خطا تمام شد** (حدود ۵ دقیقه).
- ۱۲ کانتینر همگی `healthy`؛ هر دو دامنه با TLS معتبر (Let's Encrypt) پاسخ ۲۰۰ می‌دهند؛ `ufw` (۲۲/۸۰/۴۴۳)، `fail2ban`، ۲ گیگ swap و ثبت‌کنندهٔ تغییرات (`ops-watch`) فعال است.
- سرویس‌های قبلی سرور (MCP روی پورت ۸۰۰۸ و تونل cloudflared) دست‌نخورده ماندند.
- **یک ایراد واقعی پیدا و رفع شد:** هشدارها (Alertmanager) هیچ گیرنده‌ای نداشتند (بخش ۴).

##### ۲. چگونه اجرا شد
دستور README اجرا شد؛ منو با گزینهٔ `1) Install` و پنج پاسخ (دامنهٔ فروشگاه، دامنهٔ ادمین، ایمیل ادمین، توکن بات، ID عددی ادمین) پیش رفت. نصب‌کننده خودش DNS را بررسی کرد، Docker را نصب کرد، ایمیج‌ها را ساخت، migration و bootstrap را اجرا کرد و در پایان بررسی نهایی (verification) را چاپ کرد: همه `[ok]` به‌جز یادآوری کپی کلید پشتیبان.

##### ۳. نتیجهٔ بررسی بعد از نصب
| مورد | وضعیت |
|---|---|
| کانتینرها (postgres, redis, api, worker, backup, store_web, admin_web, telegram_main, telegram_reseller, caddy, prometheus, alertmanager) | همه healthy |
| `https://shop…` و `https://admin…` | ۲۰۰، گواهی معتبر |
| `/health` و `/healthz` | ۲۰۰ |
| توکن تلگرام | معتبر (getMe) |
| مصرف | حدود ۵۰۰ مگابایت RAM برای کل پشته؛ دیسک ۲۲٪ |
| ایمیج‌ها | همگی با digest ثابت (pinned) |

##### ۴. یافته‌ها
| # | یافته | شدت | وضعیت |
|---|---|---|---|
| F1 | **Alertmanager بدون گیرنده:** نصب‌کننده توکن بات و ID ادمین را می‌داند ولی `ALERT_TELEGRAM_BOT_TOKEN` و `ALERT_TELEGRAM_CHAT_ID` را در `.env` پر نمی‌کرد؛ لاگ: «no alert receiver configured… Alerts will NOT be delivered». یعنی هر هشدار Prometheus بی‌صدا دور ریخته می‌شد. | متوسط (عملیاتی) | **رفع شد** (این برنچ) |
| F2 | ایمیل ثبت ACME در Caddy خالی است (اعلان انقضای گواهی به کسی نمی‌رسد). | کم | بدون تغییر؛ پیشنهاد در T07/T08 |
| F3 | `get.docker.com` بدون pin اجرا می‌شود. | کم | بدون تغییر؛ پیشنهاد در T07/T08 |
| F4 | هشدارهای ظاهری Caddy (فرمت Caddyfile، بافر UDP برای HTTP/3) | اطلاعاتی | بدون تغییر |

**اصلاح یک ادعای قبلی من:** در گام اول نوشتم منو روی EOF در حلقهٔ بی‌نهایت می‌ماند. این **اشتباه بود**: ورودی غلط من (پاسخ‌ها را قبل از انتخاب گزینهٔ ۱ دادم) فقط ۶ بار «Invalid choice» داد و منو در EOF با `exit 0` خارج شد. باگ نیست و چیزی برایش تغییر نکرد.

##### ۵. تغییرات این برنچ (`fix/install-alert-receiver-t05`)
- `scripts/install_server.sh`: اگر توکن بات و ID ادمین هر دو داده شده باشند، `ALERT_TELEGRAM_BOT_TOKEN` و `ALERT_TELEGRAM_CHAT_ID` هم ست می‌شوند.
- `melorin.sh`: تغییر توکن یا ID ادمین از منو، گیرندهٔ هشدار را هم هماهنگ می‌کند (مگر اینکه بات هشدار جداگانه‌ای تنظیم شده باشد).

**اعتبارسنجی روی سرور زنده:** همان مقادیر در `.env` ست شد، Alertmanager دوباره ساخته شد، هشدار آزمایشی ارسال شد: `alertmanager_notifications_total{integration="telegram"} = 1` و همهٔ شمارنده‌های شکست صفر. (یک پیام آزمایشی به تلگرام ادمین رفت.)
نکته: توکن بات اصلی برای هشدار هم استفاده می‌شود؛ اگر می‌خواهید جدا باشد یک بات دوم بسازید و `ALERT_TELEGRAM_BOT_TOKEN` را عوض کنید.

##### ۶. کارهای لازم از طرف شما
1. رمز یک‌بارمصرف و TOTP در پیام چت من و در `/root/melorin-credentials.txt` (حالت ۶۰۰) است؛ بعد از اولین ورود، رمز را عوض و فایل را حذف کنید.
2. **`/opt/melorin/secrets/backup/age-identity.txt` را بیرون از سرور کپی کنید** (تنها کلید رمزگشایی پشتیبان‌ها).
3. ربات را یک بار باز کنید و Start بزنید تا تلگرام بتواند پیام بفرستد.
4. **توکن GitHub و توکن بات تلگرام در چت نوشته شده‌اند؛ هر دو را revoke/rotate کنید** (بات: BotFather ← `/revoke`، سپس منوی `melorin` ← 3 ← 1).

</div>

### منبع / Source: `18-OPERATIONS-DEPLOYMENT-DR.md`

#### T06 — Melorin install report on a clean server (English)

Date: 2026-11-11 · Server: Ubuntu 22.04, 2 vCPU, 4 GB RAM, 40 GB disk (Hetzner) · Domains: `shop.88promax.ir` (store), `admin.88promax.ir` (admin)
Installed ref: `main` (commit `d7be664`; no release tag exists yet).

##### 1. Summary
- Installed with the exact README one-liner; it **finished without errors** (about 5 minutes).
- All 12 containers are `healthy`; both domains answer 200 with a valid Let's Encrypt certificate; `ufw` (22/80/443), `fail2ban`, 2 GiB swap and the change recorder (`ops-watch`) are active.
- The pre-existing services on the host (MCP on port 8008 and the cloudflared tunnel) were left untouched.
- **One real defect found and fixed:** Alertmanager had no receiver, so alerts were never delivered (section 4).

##### 2. How it was run
The README command was run; in the menu `1) Install` with the five answers (store domain, admin domain, admin e-mail, bot token, admin numeric Telegram ID). The installer checked DNS, installed Docker, built the images, ran migrations and bootstrap and printed its own verification: all `[ok]` except the reminder to copy the backup key off the server.

##### 3. Post-install checks
| Item | Result |
|---|---|
| Containers (postgres, redis, api, worker, backup, store_web, admin_web, telegram_main, telegram_reseller, caddy, prometheus, alertmanager) | all healthy |
| `https://shop…` / `https://admin…` | 200, valid certificate |
| `/health`, `/healthz` | 200 |
| Telegram token | valid (getMe) |
| Footprint | about 500 MB RAM for the whole stack; disk 22% |
| Images | all pinned by digest |

##### 4. Findings
| # | Finding | Severity | Status |
|---|---|---|---|
| F1 | **Alertmanager without a receiver:** the installer knows the bot token and the admin ID but never filled `ALERT_TELEGRAM_BOT_TOKEN` / `ALERT_TELEGRAM_CHAT_ID` in `.env`; log: "no alert receiver configured… Alerts will NOT be delivered". Every Prometheus alert was silently dropped. | Medium (operational) | **Fixed** (this branch) |
| F2 | Caddy's ACME contact e-mail is empty (certificate-expiry notices go nowhere). | Low | Not changed; proposed in T07/T08 |
| F3 | `get.docker.com` is piped to `sh` unpinned. | Low | Not changed; proposed in T07/T08 |
| F4 | Cosmetic Caddy warnings (Caddyfile formatting, UDP buffer for HTTP/3) | Info | Not changed |

**Correction of an earlier claim of mine:** in the first step I said the menu loops forever on EOF. That was **wrong**: my bad input (answers fed before choosing option 1) produced exactly 6 "Invalid choice" lines and the menu then exited via `exit 0` on EOF. It is not a bug and nothing was changed for it.

##### 5. Changes in this branch (`fix/install-alert-receiver-t05`)
- `scripts/install_server.sh`: when both the bot token and the admin ID are supplied, `ALERT_TELEGRAM_BOT_TOKEN` and `ALERT_TELEGRAM_CHAT_ID` are set too.
- `melorin.sh`: changing the token or admin ID from the menu keeps the alert receiver in sync (unless a separate alert bot was configured on purpose).

**Live validation:** the same values were set in `.env`, Alertmanager was recreated and a test alert fired: `alertmanager_notifications_total{integration="telegram"} = 1`, all failure counters 0. (One test message reached the admin's Telegram.)
Note: the main bot token is reused for alerts; to separate them, create a second bot and change `ALERT_TELEGRAM_BOT_TOKEN`.

##### 6. Actions for you
1. The one-time password and TOTP are in my chat reply and in `/root/melorin-credentials.txt` (mode 600); change the password after first login and delete the file.
2. **Copy `/opt/melorin/secrets/backup/age-identity.txt` off the server** (the only key that decrypts backups).
3. Open the bot once and press Start so Telegram can deliver messages.
4. **The GitHub token and the Telegram bot token were pasted in chat; revoke/rotate both** (bot: BotFather `/revoke`, then `melorin` menu → 3 → 1).

### منبع / Source: `18-OPERATIONS-DEPLOYMENT-DR.md`

<div dir="rtl" lang="fa">

#### T07 — چه چیزهایی هنگام نصب گرفته شود و چه چیزهایی بعد از نصب وارد شود (فارسی)

##### ۱. هنگام نصب خودکار از اینترنت گرفته می‌شود (مشاهده‌شده در نصب واقعی)
| دسته | چه چیزی | توضیح / ریسک |
|---|---|---|
| بستهٔ سیستم | `git`، `curl`، `openssl`، `age`، `ufw`، `fail2ban` | از مخزن Ubuntu؛ کم‌ریسک |
| Docker | Docker CE ۲۹.x از `get.docker.com` | اسکریپت بدون pin اجرا می‌شود؛ تنها حلقهٔ «اعتماد به آخرین نسخه» در زنجیرهٔ نصب |
| ایمیج پایه | postgres:16, redis:7, caddy:2, prometheus 2.55.1, alertmanager 0.27.0, node:22, nginx:1.27, python:3.12 | **همه با digest ثابت** (مطلوب)؛ حدود ۱٫۸ گیگ |
| وابستگی ساخت | pip (قفل‌شده با hash)، npm، کلید PGDG | روی خود سرور بیلد می‌شود (حدود ۴ دقیقه) |
| گواهی TLS | Let's Encrypt توسط Caddy | نیازمند DNS درست و پورت‌های ۸۰/۴۴۳ |
| بررسی | تماس `getMe` با تلگرام | فقط اعتبارسنجی توکن |

**نتیجه:** مجموعهٔ دانلود نصب درست و کم‌ریسک است. تنها پیشنهاد: نصب Docker از مخزن apt رسمی با نسخهٔ مشخص (به‌جای `get.docker.com`) و در صورت دسترسی از ایران، mirror/registry داخلی برای ایمیج‌ها (امکان `MELORIN_IMAGE_REGISTRY` از قبل در compose هست).

##### ۲. فقط همین پنج مورد هنگام نصب پرسیده شود (وضع فعلی درست است)
دامنهٔ فروشگاه، دامنهٔ ادمین، ایمیل ادمین، توکن بات، ID عددی ادمین. ایرادی در پرسیدن مقادیر بیشتر هست: هر چیز اضافه، نصب را شکننده و رازها را در `.env` پخش می‌کند. پس **نباید** اطلاعات پنل VPN، درگاه پرداخت، SMTP، S3 و غیره هنگام نصب گرفته شود؛ README هم این‌ها را زمان اجرا و رمزنگاری‌شده در دیتابیس نگه می‌دارد.

##### ۳. بعد از نصب (پنل ادمین → Settings / بخش‌های مربوط) وارد شود — ترتیب پیشنهادی
1. **ورود اول:** TOTP در برنامهٔ احراز هویت، تغییر رمز، حذف `/root/melorin-credentials.txt`.
2. **پشتیبان:** کپی `age-identity.txt` بیرون از سرور؛ سپس (اختیاری) S3 برای نسخهٔ خارج از سرور (*Settings → Integrations*).
3. **پنل‌های VPN** (Sanaei / PasarGuard) و آزمایش اتصال؛ فقط آدرس و اعتبارنامهٔ خود پنل (طبق قاعدهٔ «ملورین فقط واسطه است»).
4. **روش‌های پرداخت:** کارت‌به‌کارت و Zarinpal (فقط شارژ کیف پول).
5. **کاتالوگ:** بسته‌های فروش، قیمت، کوپن.
6. **ورود و ارتباط:** SMTP (بدون آن ورود با کد ایمیل کار نمی‌کند)، Google و Telegram login در صورت نیاز.
7. **نماینده‌ها (reseller):** دامنه + توکن بات از *Admin → Resellers* (بدون ری‌استارت).
8. **هشدارها:** ربات را Start کنید؛ در صورت تمایل بات هشدار جدا.

##### ۴. تغییر این برنچ (`chore/install-tuning-t06`)
- `docker-compose.yml`: **چرخش لاگ** برای هر ۱۲ سرویس (`json-file`، ۱۰ مگابایت × ۳ فایل). پیش‌تر لاگ هیچ‌وقت چرخانده نمی‌شد و در ماه‌ها می‌توانست دیسک ۳۸ گیگی را پر کند.
- اعتبارسنجی: `docker compose config` معتبر، گارد CI (`check_ops_p0.py`) سبز.
- (روی سرور زنده اعمال و کانتینرها دوباره ساخته شدند؛ نتیجه در پایان همین سند.)

##### ۵. پیشنهادهایی که عمداً پیاده نشد (نیاز به تصمیم شما)
| پیشنهاد | دلیل عدم اجرا |
|---|---|
| ایمیل ACME برای Caddy (`email` در Caddyfile از ایمیل ادمین) | مقدار خالی در Caddyfile خطا می‌دهد؛ نیاز به مقدار پیش‌فرض و تغییر مسیر update دارد |
| pin کردن Docker از مخزن apt | رفتار نصب را تغییر می‌دهد؛ بهتر است در یک PR جدا و با تست روی Ubuntu 22.04/24.04 باشد |
| `docker builder prune` بعد از نصب | ۱٫۶ گیگ کش بیلد قابل‌آزاد است، ولی `melorin update` را کند می‌کند؛ با ۲۸ گیگ فضای آزاد لازم نیست |
| `net.core.rmem_max` برای HTTP/3 | فقط هشدار ظاهری |
| نصب بدون منو (CI/اتوماسیون) | از قبل ممکن است: `DOMAIN=… ADMIN_DOMAIN=… ADMIN_EMAIL=… MAIN_BOT_TOKEN=… ADMIN_TELEGRAM_ID=… SKIP_BOT_PROMPT=1 bash scripts/install_server.sh` |

</div>

### منبع / Source: `18-OPERATIONS-DEPLOYMENT-DR.md`

#### T08 — What to fetch at install time vs. what to import after install (English)

##### 1. Fetched automatically at install time (observed in the real run)
| Category | What | Notes / risk |
|---|---|---|
| OS packages | `git`, `curl`, `openssl`, `age`, `ufw`, `fail2ban` | Ubuntu archive; low risk |
| Docker | Docker CE 29.x from `get.docker.com` | script is run unpinned; the only "trust the latest" link in the chain |
| Base images | postgres:16, redis:7, caddy:2, prometheus 2.55.1, alertmanager 0.27.0, node:22, nginx:1.27, python:3.12 | **all pinned by digest** (good); about 1.8 GB |
| Build deps | pip (hash-locked), npm, PGDG key | built on the host (about 4 minutes) |
| TLS certificates | Let's Encrypt via Caddy | needs correct DNS and free ports 80/443 |
| Check | `getMe` call to Telegram | token validation only |

**Verdict:** the download set is correct and low-risk. Only suggestion: install Docker from the official apt repository with a pinned version instead of `get.docker.com`, and (if reachability from Iran is a concern) a local registry/mirror for the images (`MELORIN_IMAGE_REGISTRY` already exists in compose).

##### 2. Ask only these five things at install time (current behaviour is right)
Store domain, admin domain, admin e-mail, bot token, admin numeric ID. Asking for more makes the install fragile and spreads secrets into `.env`. So VPN-panel data, payment gateways, SMTP, S3 etc. should **not** be collected at install; the README already keeps them runtime-configured and encrypted in the database.

##### 3. Import after install (Admin panel → Settings / relevant sections) — suggested order
1. **First login:** TOTP in an authenticator app, change the password, delete `/root/melorin-credentials.txt`.
2. **Backups:** copy `age-identity.txt` off the server; then (optional) S3 for off-site copies (*Settings → Integrations*).
3. **VPN panels** (Sanaei / PasarGuard) and a connection test; only the panel URL and credentials (Melorin is only a mediator).
4. **Payment methods:** card-to-card and Zarinpal (wallet top-up only).
5. **Catalog:** sales bundles, prices, coupons.
6. **Login and mail:** SMTP (without it e-mail-code login is unavailable), Google and Telegram login if needed.
7. **Resellers:** domain + bot token in *Admin → Resellers* (no restart).
8. **Alerts:** press Start on the bot; optionally a separate alert bot.

##### 4. Change in this branch (`chore/install-tuning-t06`)
- `docker-compose.yml`: **log rotation** for all 12 services (`json-file`, 10 MB × 3 files). Previously logs were never rotated and could fill the 38 GB disk over months.
- Validation: `docker compose config` valid, CI guard (`check_ops_p0.py`) green.
- (Applied on the live server and containers recreated; result at the end of this document.)

##### 5. Suggestions deliberately not implemented (need your decision)
| Suggestion | Why not done |
|---|---|
| ACME e-mail for Caddy (`email` in the Caddyfile from the admin e-mail) | an empty value breaks the Caddyfile; needs a default and an update-path change |
| Pin Docker from the apt repo | changes install behaviour; better as a separate PR tested on Ubuntu 22.04/24.04 |
| `docker builder prune` after install | frees 1.6 GB but slows `melorin update`; unnecessary with 28 GB free |
| `net.core.rmem_max` for HTTP/3 | cosmetic warning only |
| Menu-less install (CI/automation) | already possible: `DOMAIN=… ADMIN_DOMAIN=… ADMIN_EMAIL=… MAIN_BOT_TOKEN=… ADMIN_TELEGRAM_ID=… SKIP_BOT_PROMPT=1 bash scripts/install_server.sh` |

### منبع / Source: `history/I41_BACKUP_RESTORE_DRILL.md`

#### I41: backup and restore drill

Added `scripts/backup_restore_drill.sh`, which decrypts and checksum-verifies a
backup, restores it into a uniquely named temporary PostgreSQL database, checks
that public tables exist, and removes that temporary database on exit.

Run it with:

```bash
BACKUP_ARCHIVE=... \
BACKUP_IDENTITY_FILE=... \
MELORIN_DATABASE_URL=postgresql://user:password@host:5432/melorin \
MELORIN_RPO_HOURS=24 \
MELORIN_RTO_HOURS=8 \
make restore-drill
```

The repository now has an executable acceptance path for the documented RPO
of 24 hours and RTO of 8 hours. A passing static check is not runtime evidence:
the drill must run against a real encrypted backup and PostgreSQL target in
CI/staging, with its timestamp and duration attached to the release matrix.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
