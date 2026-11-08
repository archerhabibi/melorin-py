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
| Decision 2 | **Configurable retention days** per panel for the `aligned` lifecycle policy (`PUT …/lifecycle-policy {policy, retention_days}`); the additive migration adds `panels.expected_retention_days`. Melorin only expects and warns; it never writes the panel. | `settings_drift.py`, `panel_phase5.py` |
| L1 | **Prometheus works again.** `infra/` is mounted as a directory (no stale rules after `git pull`); `secrets/metrics-token` is owned by `nobody` (65534, mode 0600) and rewritten in place. | `docker-compose.yml`, `infra/prometheus.yml`, `scripts/install_server.sh` |

| R4 | **Traffic warnings read the panel's own numbers.** The 80/90 % level is computed from the reading just taken from the panel (`notices.percent_of`), not from the copy written a line earlier. | `sync.apply_remote`, `notices.percent_of` |
| R6 | **Admin account list is live** (same flag `vpn.live_view`): usage, expiry, health from the panel; panel down → no numbers, `health=unavailable`. | `live.overlay_rows`, `admin/directory.py` |
| R5 | **Analytics tell the truth about their source.** Stored traffic sums are labelled `traffic_source=last_known` with `traffic_as_of`; each panel's own users/online counts (from its monitoring snapshot) are added under `vpn.panels`. | `admin/analytics.py::_snapshot` |
| PG-05 / N4 | **Least-privilege service access.** Role `melorin-service` is built from `CAPABILITY_REQUIREMENTS` (the single source) and withholds node/admin/core create+delete and all API-key management. `provision` creates role + admin + key (owner credential used once), **verifies the new key is the service role (not owner, nothing missing) before switching**, stores it encrypted, never returns/logs it, and leaves the old owner key for the operator to revoke. `rotate` replaces the key (verify first, delete old after). A rejected key is deleted and Melorin stays on the old credential. | `service_access.py`, `adapters/pasarguard/access.py`, `admin/panel_phase5.py` (`/admin/panels/{id}/service-access[/keys|/provision|/rotate]`) |

| Decision 6 / L8 | **The panel is the capacity truth.** New and existing destinations use `capacity_source=panel` (migration `0052`); `effective_load` still falls back to Melorin's count until the panel's figure has been read. Stored panel numbers (`servers.panel_total_users`, `panel_admins.used_traffic_bytes/total_users`) are now shown with their age (`panel_users_as_of`, `as_of`, `last_known`). | `capacity.py`, `governance.py`, migration `0052` |
| PG-06 texts | **Per-store customer notice wording.** `PUT/GET /admin/stores/{id}/vpn-notice-texts` (`{kind: {title, body}}`, placeholders `{store}` and `{level}` only, no `str.format`, length-limited, 422 on junk). Platform text is the fallback; saving texts never touches the warning levels. | `notices.py`, `panel_ops.py` |
| PG-06 digest | **Opt-in daily digest for the store owner** (`PUT /admin/stores/{id}/vpn-digest`, off by default; worker `store_digest_job` 17:00 UTC). It reports only what Melorin owns (notices sent in 24 h, open discrepancies, sell-block reason), **no usage/expiry numbers**; one per store per day; empty day = nothing sent. | `digest.py`, `worker/jobs.py` |
| Fix | `state_hint` no longer breaks on account stand-ins without `remote_status` (a test on the branch was red). | `inquiry.py` |

## Switch-on order (staging first)

1. Deploy, run `alembic upgrade head` (additive; head: see docs/STATUS.md).
2. Server, once: `chown 65534:65534 /opt/melorin/secrets/metrics-token && chmod 600 …`, then `docker compose up -d --force-recreate prometheus`. Check: target `up`, 21 rules loaded, `melorin_panel_nodes` returns data.
3. Admin → settings: set `vpn.live_view = true` and look at the customer account list. Panel down must show "temporarily unavailable".
4. Watch one day of `expiry_job` logs (`expiry: live read failed`), then keep it.

## PG-05 rollout (one panel, staging first)

1. `GET /admin/panels/{id}/service-access` → read `plan` (grants / withheld) and the current level (`owner` today).
2. `POST …/service-access/provision` with `confirm_name` = the panel's name (the stored credential is used if it is owner-level, or pass `bootstrap`).
3. Check the panel page: level `least_privilege`, all capabilities still on. Then revoke the old owner key **on the panel** (Melorin does not delete it).
4. Rotation later: `POST …/rotate` with an owner `bootstrap` credential (needed because the service role cannot manage keys).
Request shapes (`AdminRoleCreate`, `APIKeyCreate`) were read from the live panel's OpenAPI 5.6.0; the role was **not** applied to the live panel from this work, so run steps 1-3 on staging first.

## Not done yet (in priority order)

1. **Live check of PG-05** on the test panel (see rollout above); not run from this work.
3. **R7–R10** stop writing the copied columns (`traffic_used_bytes`, `online_at`, `lifetime_used_traffic`, `subscription_url`, `links`, orphan/admin traffic, `servers.panel_total_users`), split "sold" from "now" (`expires_at`/`traffic_limit_bytes`), then drop the columns in a later migration. Deliberately **not** done in one step: `limits_mismatch`, plan settlement and the delivery message still read them.
4. PG-04: "re-create on panel" and "link to existing panel user" issue actions; "assign manual account to a store/customer".
5. PG-12 `melorin-store` role and `sub_template`/`custom_variables` branding; per-store usage report in the reseller bot; assign a manual account to a store/customer; admin-only online IP view; N10 internal-network exception. (PG-02 limited/on_hold text and PG-06 digest/texts are done above.)
6. Operator only: enable panel backup (`MELORIN_PANEL_BACKUP_*`, L2), rotate the Telegram token in `notification_settings`, fix node certificates (`server_ca`), Caddy healthcheck.

## Merge note (8 Nov 2026)
`feat/pasarguard-phase6-mediator` and `feat/pasarguard-mediator-rework` were unified on this branch. The rework branch was the
superset (R1 PanelLiveView, R2, R3, L4, retention days, one additive migration). From phase6 only the `link_existing` issue action
(PG-04, for `missing_on_panel`) and the `orphans_manual` count in the reconciliation summary were added.
