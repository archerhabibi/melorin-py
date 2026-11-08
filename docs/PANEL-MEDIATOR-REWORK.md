# PasarGuard mediator rework: what is done, what is next

Branch `feat/pasarguard-mediator-rework` (from `main` @ `9a4a971`). Source: `MELORIN-PASARGUARD-GAP-ANALYSIS` and `…-LIVE-VERIFICATION` (8 Nov 2026).
Rule: **Melorin is a mediator**. Used traffic, limit, expiry and status belong to the panel; Melorin reads them, it does not own a copy.

## Done in this branch (tests: `test_mediator_rework_db.py`, `test_panel_live_view_db.py`; full suite green)

| ID | Change | Where |
|---|---|---|
| R3 | **Fail-closed refunds.** A return always does a fresh panel read (the 15 s rate limit no longer applies to it). Panel down or user missing there → `503 PANEL_UNAVAILABLE`, no refund. Accounts without a panel pass. | `inquiry.refresh_from_panel(strict=True)`, `returns.prepare_return` |
| R2 | **The panel decides expiry.** `expiry_job` no longer marks panel accounts `expired` by Melorin's clock: an overdue account is re-read live and the panel's status/expiry is applied (a renewal done on the panel moves the date; a panel that does not answer changes nothing). Accounts without a panel keep the local clock. Max 200 live reads per run. | `worker/jobs.py::expiry_job` |
| L4 | Open issues of archived/revoked accounts close themselves (`resolution=account_inactive`). | `issues.close_for_inactive`, `reconcile_panel` |
| R1 | **PanelLiveView.** Live expiry/usage/limit/health for a page of accounts, one adapter per panel, bounded concurrency, 20 s in-memory cache. Panel cannot answer → `live=false`, no numbers, text "temporarily unavailable" (decision 9). Behind setting `vpn.live_view` (default **off**, so nothing changes until you switch it on). Wired into the customer account routes. | `modules/vpn/live.py`, `router.py`, `VpnAccountOut.live/live_note` |
| PG-04 / decision 1 | Orphans can be recorded as **manual account** (`POST /admin/panel-orphans/{id}/manual`) and re-opened (`…/reopen`). Never deleted; becomes `gone` when the panel user disappears. | `panel_ops.py`, `reconcile._record_orphans` |
| Decision 2 | **Configurable retention days** per panel for the `aligned` lifecycle policy (`PUT …/lifecycle-policy {policy, retention_days}`); migration `0051` adds `panels.expected_retention_days`. Melorin only expects and warns; it never writes the panel. | `settings_drift.py`, `panel_phase5.py` |
| L1 | **Prometheus works again.** `infra/` is mounted as a directory (no stale rules after `git pull`); `secrets/metrics-token` is owned by `nobody` (65534, mode 0600) and rewritten in place. | `docker-compose.yml`, `infra/prometheus.yml`, `scripts/install_server.sh` |

## Switch-on order (staging first)

1. Deploy, run `alembic upgrade head` (0051, additive).
2. Server, once: `chown 65534:65534 /opt/melorin/secrets/metrics-token && chmod 600 …`, then `docker compose up -d --force-recreate prometheus`. Check: target `up`, 21 rules loaded, `melorin_panel_nodes` returns data.
3. Admin → settings: set `vpn.live_view = true` and look at the customer account list. Panel down must show "temporarily unavailable".
4. Watch one day of `expiry_job` logs (`expiry: live read failed`), then keep it.

## Not done yet (in priority order)

1. **PG-05 / N4** least-privilege `melorin-service` admin + custom role + API-key create/rotate/revoke. Needs a design pass and a live panel to test; not started. Until then Melorin still uses the owner's API key (L3).
2. **R4–R6** drive traffic notices, analytics (`admin/analytics.py`) and admin lists from the panel (events / aggregates / PanelLiveView) instead of the stored columns. `PanelLiveView.read` is the building block; only the customer routes use it so far.
3. **R7–R10** stop writing the copied columns (`traffic_used_bytes`, `online_at`, `lifetime_used_traffic`, `subscription_url`, `links`, orphan/admin traffic, `servers.panel_total_users`), split "sold" from "now" (`expires_at`/`traffic_limit_bytes`), then drop the columns in a later migration. Deliberately **not** done in one step: `limits_mismatch`, plan settlement and the delivery message still read them.
4. PG-04: "re-create on panel" and "link to existing panel user" issue actions; "assign manual account to a store/customer".
5. PG-02 `limited` → renewal offer and `on_hold` customer text; PG-06 daily digest / per-store texts; PG-12 `melorin-store` role and branding; admin-only online IP view; N10 internal-network exception.
6. Operator only: enable panel backup (`MELORIN_PANEL_BACKUP_*`, L2), rotate the Telegram token in `notification_settings`, fix node certificates (`server_ca`), Caddy healthcheck.

## Merge note (8 Nov 2026)
`feat/pasarguard-phase6-mediator` and `feat/pasarguard-mediator-rework` were unified on this branch. The rework branch was the
superset (R1 PanelLiveView, R2, R3, L4, retention days, migration 0051). From phase6 only the `link_existing` issue action
(PG-04, for `missing_on_panel`) and the `orphans_manual` count in the reconciliation summary were added.
