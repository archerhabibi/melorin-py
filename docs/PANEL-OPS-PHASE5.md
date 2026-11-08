# PasarGuard Phase 5 - Metrics and alerts, settings drift, panel backup

Covers PG-14, PG-15 and PG-16 of `MELORIN-PASARGUARD-MANAGEMENT`. Migration: `0050_pasarguard_phase5`.
Everything is built once in the core API; the admin web (Panels -> "شاخص و پشتیبان" tab) only consumes it. All endpoints need a Melorin admin.

## Principles applied

* **A scrape never waits for a panel.** The worker takes one live reading per panel (`panel_metrics.run_snapshots`, every 2 minutes) and
  stores it on `panels.metrics_snapshot`. `/metrics` only renders gauges from the database.
* **No data is "unknown", never a fake zero.** A gauge with no reading (credential cannot read `system`, panel down, no nodes) is simply not emitted.
  Gone or disabled panels stop reporting.
* **Read-only against the panel.** The drift check reads `GET /api/settings`; it never writes a setting. The lifecycle policy only changes what
  *Melorin* expects, and is audited with a reason.
* **A failed read never invents or clears drift.** The previous verdict stays and the error is shown next to it.
* **No secret leaves the panel's settings.** Findings carry booleans, counts and origins only (never a webhook secret, token or password).
* **Panel backups are their own series.** `melorin_backup_age_seconds{target="panel"}` cannot trip `MelorinBackupStale`, and a deployment
  that does not back up the panel is "not in use", not "stale".

## PG-14 Metrics and alerts

| Gauge | Labels | Source |
|---|---|---|
| `melorin_panel_up` | panel | health status (`unhealthy` = 0) |
| `melorin_panel_nodes` | panel, status | `panel_nodes` rows (connected / connecting / disabled / error) |
| `melorin_panel_users`, `melorin_panel_online_users` | panel[, status] | snapshot of `GET /api/system` |
| `melorin_panel_cpu_ratio`, `_mem_ratio`, `_disk_ratio` | panel | snapshot (0..1) |
| `melorin_panel_api_latency_seconds` | panel | snapshot (health call duration) |
| `melorin_panel_snapshot_age_seconds` | panel | now - snapshot time (stale = job or panel down) |
| `melorin_panel_webhook_lag_seconds` | panel | silence of a connected live-event channel |
| `melorin_panel_settings_drift` | panel | number of drifting findings (PG-15) |
| `melorin_reconcile_open_issues` | kind | open reconciliation issues |
| `melorin_reconcile_lag_seconds` | - | oldest un-reconciled account |
| `melorin_server_capacity_ratio` | server | accounts / capacity |

Alert rules (`infra/alerts.yml`, group `melorin-panels`): `MelorinPanelNodeDown` (critical), `MelorinPanelDegraded`, `MelorinPanelApiSlow`,
`MelorinPanelResourcesHigh`, `MelorinPanelMetricsStale`, `MelorinReconcileLagHigh`, `MelorinCapacityHigh`, `MelorinPanelSettingsDrift`,
`MelorinPanelBackupStale` (critical). The same conditions feed `set_alert` so the admin UI and Prometheus agree.

| Endpoint | Purpose |
|---|---|
| `GET /admin/panels/{id}/metrics` | the last reading, its age and node counts |

## PG-15 Settings drift and lifecycle policy

The check compares the panel's settings with what Melorin needs:

| Finding | Drift when |
|---|---|
| `webhook` | live events are connected in Melorin but the panel has them off, or Melorin's URL is no longer a target |
| `subscription_prefix` | the panel's `url_prefix` origin differs from `sub_base_url` |
| `expired_cleanup` | the panel auto-deletes expired users sooner than the lifecycle policy allows |
| `hwid` | never (information only: the device-limit policy belongs to the panel) |

**Lifecycle policy** (`panels.expired_cleanup_policy`), the open decision "panel auto-delete of expired users":

* `keep` (default) - the panel must NOT auto-delete expired users; any retention is drift, because Melorin would see those accounts as `missing_on_panel`.
* `aligned` - the panel may delete expired users, but not before the renewal grace period (`GRACE_DAYS`); a shorter retention is drift.

The worker re-checks hourly (minute 25); the admin can check on demand. Event Center announces only the change 0 -> N and N -> 0 drifting findings (by key, never a value read from the panel), so an unfixed drift does not repeat every hour.

| Endpoint | Purpose |
|---|---|
| `GET  /admin/panels/{id}/settings-drift` | last verdict, policy and findings |
| `POST /admin/panels/{id}/settings-drift/check` | read the panel now (read-only) |
| `PUT  /admin/panels/{id}/lifecycle-policy` | `{policy: keep|aligned, reason}` (audited) |

## PG-16 Panel backup and recovery

`scripts/backup_panel.sh` produces `panel-<UTC stamp>.tar.age` (age-encrypted, checksum, retention, optional S3 copy; exit 3 = local OK, off-site
failed) holding `panel-db.dump` (the panel's database) and/or `panel-data.tar` (directories such as `/var/lib/pasarguard`).
`panel_backup_job` runs it daily at 02:40 and records `BackupRun(target="panel")`. `scripts/verify_panel_backup.sh` is a NON-destructive
restore test (`BACKUP_ARCHIVE`, `BACKUP_IDENTITY_FILE` = the age private key kept off the server): it checks the checksum, decrypts into a temp directory,
lists the database dump with `pg_restore --list` and the data archive with `tar`, and restores nothing. Run it after every change and at least monthly.

Configure (both optional, at least one needed): `MELORIN_PANEL_BACKUP_DATABASE_URL` (the panel's database port, not PgBouncer in transaction mode)
and `MELORIN_PANEL_BACKUP_PATHS` (directories mounted into the worker). The worker image carries `pg_dump` 16 **and 17**: the panel's TimescaleDB
is PostgreSQL 17 and `pg_dump` refuses a server newer than itself.

| Endpoint | Purpose |
|---|---|
| `GET /admin/panel-backups` | state (`ok`/`stale`/`not_configured`), last success, recent runs |

Recovery procedure: `docs/RUNBOOK.md`, "Panel lost: how Melorin converges".

## Tests

`apps/api/tests/test_pasarguard_phase5_ops_maturity.py` (gauges, absence rules, snapshot failures, drift findings and policy, backup state, auth on every
endpoint, alert-rule and script contracts, worker image clients) and `apps/admin-web/tests/panel-phase5.test.jsx`.
