# PasarGuard mediator rework: what is done, what is next

Branch `feat/pasarguard-mediator-rework` (from `main` @ `9a4a971`). Source: `MELORIN-PASARGUARD-GAP-ANALYSIS` and `…-LIVE-VERIFICATION` (8 Nov 2026).
Rule: **Melorin is a mediator**. Used traffic, limit, expiry and status belong to the panel; Melorin reads them, it does not own a copy.

## Done in this branch (tests: `test_mediator_rework_db.py`, `test_panel_live_view_db.py`; full suite green)

| ID | Change | Where |
|---|---|---|
| R3 | **Fail-closed refunds.** A return always does a fresh panel read (the 15 s rate limit no longer applies to it). Panel down or user missing there → `503 PANEL_UNAVAILABLE`, no refund. Accounts without a panel pass. | `inquiry.refresh_from_panel(strict=True)`, `returns.prepare_return` |
| R2 | **The panel decides expiry.** `expiry_job` no longer marks panel accounts `expired` by Melorin's clock: an overdue account is re-read live and the panel's status/expiry is applied (a renewal done on the panel moves the date; a panel that does not answer changes nothing). Accounts without a panel keep the local clock. Max 200 live reads per run. | `worker/jobs_accounts.py::expiry_job` |
| L4 | Open issues of archived/revoked accounts close themselves (`resolution=account_inactive`). | `issues.close_for_inactive`, `reconcile_panel` |
| R1 | **PanelLiveView.** Live expiry/usage/limit/health for a page of accounts, one adapter per panel, bounded concurrency, 20 s in-memory cache. Panel cannot answer → `live=false`, no numbers, text "temporarily unavailable" (decision 9). Setting `vpn.live_view` (default **on** since R9/R10: with no stored copy there is nothing to fall back on; switching it off shows no panel numbers). Wired into the customer account routes. | `modules/vpn_accounts/live.py`, `router.py`, `VpnAccountOut.live/live_note` |
| PG-04 / decision 1 | Orphans can be recorded as **manual account** (`POST /admin/panel-orphans/{id}/manual`), re-opened (`…/reopen`) and **assigned to a store customer** (`…/assign`, see the section below: zero-price `manual` order that is not a sale). Never deleted; becomes `gone` when the panel user disappears or is assigned. | `panel_orphans.py`, `manual_assign.py`, `domain/order_kinds.py`, `reconcile._record_orphans` |
| Decision 2 | **Configurable retention days** per panel for the `aligned` lifecycle policy (`PUT …/lifecycle-policy {policy, retention_days}`); the additive migration adds `panels.expected_retention_days`. Melorin only expects and warns; it never writes the panel. | `settings_drift.py`, `panel_monitoring.py` |
| L1 | **Prometheus works again.** `infra/` is mounted as a directory (no stale rules after `git pull`); `secrets/metrics-token` is owned by `nobody` (65534, mode 0600) and rewritten in place. | `docker-compose.yml`, `infra/prometheus.yml`, `scripts/install_server.sh` |

| R4 | **Traffic warnings read the panel's own numbers.** The 80/90 % level is computed from the reading just taken from the panel (`notices.percent_of`), not from the copy written a line earlier. | `sync.apply_remote`, `notices.percent_of` |
| R6 | **Admin account list is live** (same flag `vpn.live_view`): usage, expiry, health from the panel; panel down → no numbers, `health=unavailable`. | `live.overlay_rows`, `admin/directory.py` |
| R5 | **Analytics tell the truth about their source.** Stored traffic sums are labelled `traffic_source=last_known` with `traffic_as_of`; each panel's own users/online counts (from its monitoring snapshot) are added under `vpn.panels`. | `reports/analytics.py::_snapshot` |
| PG-05 / N4 | **Least-privilege service access.** Role `melorin-service` is built from `CAPABILITY_REQUIREMENTS` (the single source) and withholds node/admin/core create+delete and all API-key management. `provision` creates role + admin + key (owner credential used once), **verifies the new key is the service role (not owner, nothing missing) before switching**, stores it encrypted, never returns/logs it, and leaves the old owner key for the operator to revoke. `rotate` replaces the key (verify first, delete old after). A rejected key is deleted and Melorin stays on the old credential. | `service_access.py`, `adapters/pasarguard/access.py`, `admin/panel_monitoring.py` (`/admin/panels/{id}/service-access[/keys|/provision|/rotate]`) |

| Decision 6 / L8 | **The panel is the capacity truth.** New and existing destinations use `capacity_source=panel` (migration `0052`); `effective_load` still falls back to Melorin's count until the panel's figure has been read. Stored panel numbers (`servers.panel_total_users`, `panel_admins.used_traffic_bytes/total_users`) are now shown with their age (`panel_users_as_of`, `as_of`, `last_known`). | `capacity.py`, `governance.py`, migration `0052` |
| PG-06 texts | **Per-store customer notice wording.** `PUT/GET /admin/stores/{id}/vpn-notice-texts` (`{kind: {title, body}}`, placeholders `{store}` and `{level}` only, no `str.format`, length-limited, 422 on junk). Platform text is the fallback; saving texts never touches the warning levels. | `notices.py`, `store_vpn_notices.py` |
| PG-06 digest | **Opt-in daily digest for the store owner** (`PUT /admin/stores/{id}/vpn-digest`, off by default; worker `store_digest_job` 17:00 UTC). It reports only what Melorin owns (notices sent in 24 h, open discrepancies, sell-block reason), **no usage/expiry numbers**; one per store per day; empty day = nothing sent. | `digest.py`, `worker/jobs_reports.py` |
| PG-12 / L6 (plan only) | `GET /admin/panels/{id}/store-role-plan`: the least-privilege `melorin-store` role (users CRUD + groups read; no `api_keys`, admins, nodes, settings). **Not created on the panel by Melorin**; create it on staging, test one store admin, then switch `panel_admins.ROLE`. | `store_role.py` |
| R8 (read side) | **Subscription link is read from the panel.** The QR routes (customer and store owner) use `live.current_link`: the panel's current link (it changes on `revoke_sub`); the stored value is only the *delivery snapshot* and is used when the panel cannot answer. Sync still refreshes that snapshot (needed by the subscription check); no reader treats it as truth. | `live.current_link`, `vpn/router.py`, `reseller/routes/accounts.py` |
| Fix | `state_hint` no longer breaks on account stand-ins without `remote_status` (a test on the branch was red). | `inquiry.py` |

| Decision 5 | **Admin-only connection view.** New capability `ip_ops` (needs `nodes.stats` + `users.read`) and tool `connections`: live connection IPs per node and the subscription-fetch history (`GET …/admin/vpn-accounts/{id}/tools/connections?limit&offset`). Owners and customers do not have the tool (403 before any panel call). Nothing is stored; each view is audited (`vpn_account.connections_viewed`) with **counts only, never the IPs**. One half failing (a node down, a missing permission) does not hide the other; both failing is `503 PANEL_UNAVAILABLE`. Response shapes were checked against the live panel's source (`UserIPListAll`, `UserSubscriptionUpdateList`). | `adapters/pasarguard/users.py` (`online_ips`, `subscription_updates`), `account_tools.connections`, `tools_router.py`, tests `test_admin_connections_db.py` |

## R9 / R10 + dropping the copied columns: design (8 Nov 2026, migration `0054`)

Melorin has not been released, so this is done in ONE step (no "one release without readers" waiting period): readers are moved first,
then the columns go in the same migration.

### What a `vpn_accounts` row means afterwards
| Column | Meaning | Written by |
|---|---|---|
| `sold_expires_at` (was `expires_at`) | **Sold entitlement**: the expiry Melorin last *sold or applied* (purchase, renewal, plan change, compensation, bulk extend, "accept panel"). Used where Melorin itself decides: renewal window, SQL list filters/counters, expiry/near-expiry scheduling, bulk selection, `limits_mismatch` baseline, delivery text, audit. **Never** copied from a sync. | acts only (`sync.record_sale`) |
| `sold_traffic_bytes` (was `traffic_limit_bytes`) | Sold package volume (0 = unlimited). Same rules. | acts only |
| `delivery_snapshot` (new, JSON) | What the customer was handed at delivery: `{subscription_url, links, taken_at}`. Written once at provisioning. Fallback only when the panel cannot answer (QR/delivery message). Not refreshed by sync. | provisioning |
| `status` | The *derived display state* (active/limited/expired/suspended…). Updated from the panel by sync/events/live reads; allowed because SQL chips and sell logic need a bucket. | sync / events / acts |
| dropped | `traffic_used_bytes`, `subscription_url`, `links`, `remote_status`, `online_at`, `lifetime_used_traffic` | nothing |

"Now" values (expiry now, limit now, used, remote status, last seen, link) are **only** read from the panel (`live.py`, short in-memory cache).
The API field names (`expires_at`, `traffic_limit_bytes`, `traffic_used_bytes`, `subscription_url`, `links`) do not change, so no client breaks;
`traffic_used_bytes` becomes nullable (`null` = panel did not answer), and `live=false` tells the client the numbers are Melorin's entitlement.

### Behaviour changes
* **`sync.apply_remote` no longer copies state.** It updates `status`, `last_synced_at`, queued-plan settlement and the notices (from the reading it was given). It never writes `sold_*`.
* **`sync.record_sale(account, expires_at, traffic_bytes)`** is the single writer of the entitlement. Every Melorin act calls it with the absolute values it just applied (R10).
* **`limits_drift`** compares the panel with the *sold* entitlement and now stays visible (`limits_mismatch` auto-closes when the panel and the entitlement agree again). New issue action **`accept_panel`** rebases the entitlement on the live panel values (audited). An ignored drift is not re-opened while it is identical.
* **Returns:** `evaluate()` takes the usage as a parameter. Lists pass the live reading if they have one (otherwise the usage rule is advisory-skipped); `prepare_return` always passes the strict fresh reading, so the money decision never uses a stored number. `AccountReturn.used_bytes/limit_bytes` stay as the audit snapshot.
* **Analytics:** no stored usage sums; sold volume is summed from `sold_traffic_bytes` and labelled as sold, usage comes from each panel's monitoring snapshot.
* **`expiry_job`** selects candidates by `sold_expires_at <= now` and decides on a live read (already so since R2); on-hold accounts are recognised from the live reading, not from a stored status.

### Order of work (each step = one commit, suite green)
1. Model + migration `0054` (rename/add/drop, no data carried: unreleased). 2. `sync`/`inquiry`/`live`/`returns` (read side). 3. Acts (provisioning, renewal, plans, bulk, account_tools, runner, recreate, admin orders) call `record_sale`. 4. Reconcile/issues (`accept_panel`), analytics, directory, subscription check, delivery. 5. Tests, docs regeneration, patch.

## Switch-on order (staging first)

1. Deploy, run `alembic upgrade head`. `0054` renames and drops columns (Melorin is unreleased; `delivery_snapshot` is back-filled from the old link columns). Verified on PostgreSQL 16: upgrade with data, downgrade, re-upgrade, `alembic check` clean.
2. Server, once: `chown 65534:65534 /opt/melorin/secrets/metrics-token && chmod 600 …`, then `docker compose up -d --force-recreate prometheus`. Check: target `up`, 21 rules loaded, `melorin_panel_nodes` returns data.
3. Look at the customer account list (`vpn.live_view` is on by default). Panel down must show "temporarily unavailable".
4. Watch one day of `expiry_job` logs (`expiry: live read failed`), then keep it.

## PG-05 rollout (one panel, staging first)

1. `GET /admin/panels/{id}/service-access` → read `plan` (grants / withheld) and the current level (`owner` today).
2. `POST …/service-access/provision` with `confirm_name` = the panel's name (the stored credential is used if it is owner-level, or pass `bootstrap`).
3. Check the panel page: level `least_privilege`, all capabilities still on. Then revoke the old owner key **on the panel** (Melorin does not delete it).
4. Rotation later: `POST …/rotate` with an owner `bootstrap` credential (needed because the service role cannot manage keys).
Request shapes (`AdminRoleCreate`, `APIKeyCreate`) were read from the live panel's OpenAPI 5.6.0; the role was **not** applied to the live panel from this work, so run steps 1-3 on staging first.

## PG-04 decision 1 - assigning a manual account (DECIDED and built, 8 Nov 2026)

`POST /admin/panel-orphans/{id}/assign {store_id, user_id, product_id, server_id?, note?}` gives a panel user (status `open` or `manual`) to a store customer.

**Why an order exists:** `vpn_accounts.order_id` / `product_id` are NOT NULL, so the account hangs on a synthetic order, `kind="manual"`, `total=0`, `payment_method="free"`, `channel="admin"`, `reseller_cost=NULL`, `status=completed`, `idempotency_key=manual:<orphan id>`. Melorin is unreleased, so the schema was not bent for it: no migration.

**The rule (one module, `domain/order_kinds.py`: `NON_REVENUE_KINDS = {test, manual}`):**

| Where | Manual order |
|---|---|
| Sales / revenue / order counts (admin analytics, timeseries, `/reports/stores/{id}/sales`, reseller report, reseller API report) | **excluded** (the order is not even counted as an order) |
| Reseller commission / wholesale cost | **excluded** (`reseller_cost` is NULL: no debit, nothing to settle) |
| Referral reward and commission, "store history" for new-customer rules | **excluded** (also `total=0`) |
| Loyalty club points, first-order bonus, tier progress | **excluded** |
| Returns / refunds | impossible (`kind != purchase`, nothing was paid) |
| Event centre / Telegram orders topic | silent; the audit trail has `vpn_account.manual_assigned` |
| Renewal of the account | allowed: a **new `renewal` order with a real price**, counted like any sale |

`test` orders already followed the loyalty/referral/event part of this rule; they are now under the same constant (admin sales charts still show `test` as its own kind, as before).

**What it does and does not do:** reads the user from the panel *now* (strict: panel does not answer -> `503 PANEL_UNAVAILABLE`, nothing created) and rebases the sold entitlement on it through `sync.record_sale` (same idea as `accept_panel`). It writes **nothing** to the panel. The orphan becomes `gone` with a note (same end state as `link_existing`). Refused with a clear code: orphan `gone` / `ignored` (re-open first), customer not an active member of the store (`NOT_A_MEMBER`), test or archived product, username taken, user missing on the panel. `owner_matches=false` in the answer means the panel user belongs to another PasarGuard admin than the store's: the next reconcile opens `owner_mismatch` and an admin decides `fix_owner` (Melorin never moves it by itself).

Tests: `apps/api/tests/test_manual_assign_db.py` (15).

## PG-12 - the `melorin-store` role (explicit action, 8 Nov 2026)
`POST /admin/panels/{id}/store-role/apply {confirm_name, bootstrap}` creates (or realigns) the role `melorin-store` (users create/read/update/delete + groups read; **no** `api_keys`, admins, nodes, hosts, settings) with an owner credential used for that one request and never stored, then sets `panel.config.admin_role`. New and re-synced store admins get the role (`panel_admins._push` passes it on every ensure); existing admins change on their next sync. `POST .../store-role/revert` returns to the stock role and writes nothing to the panel. Both are typed-name confirmed and audited (`panel.store_role.applied|reverted`). Nothing runs automatically (decision 3).
The page itself is a fixed base template shipped in `infra/sub-template/index.html` and installed by the panel operator (`CUSTOM_TEMPLATES_DIRECTORY` + `SUBSCRIPTION_PAGE_TEMPLATE=subscription/index.html`, restart the panel). Stores never supply HTML (XSS on the subscription domain). Verified live (9 Nov 2026): `custom_variables` reach the template as `user.admin.custom_variables` (see the branding section). Roll out on staging first: apply, resync one test store admin, do a create/renew/delete round trip, then the rest.

## PG-12 - per-store subscription branding (9 Nov 2026)
The store owner edits three plain fields, `PUT /stores/{id}/reseller/sub-branding {display_name, support_url, logo_url}` (plain text, https links only, logo must be an image URL, no markup; stored in `stores.branding["sub"]`, no migration). Saving sends nothing to a panel.
The admin puts them on the panel with an explicit action: `GET /admin/stores/{store_id}/sub-branding/{panel_id}` (read-only: wanted vs. what the panel holds), `POST .../apply {confirm_name}` and `POST .../revert {confirm_name}` (typed panel name, audited as `panel.sub_branding.applied|reverted` with key names and a digest, never values). Apply writes exactly three keys into the store admin's `custom_variables` (`melorin_brand_name`, `melorin_support_url`, `melorin_logo_url`), keeps every other key, **reads the admin back** and restores the previous values if the panel did not keep them. Nothing runs automatically (decision 3).
Melorin never writes `sub_template` or HTML: a store-chosen template would run on the subscription domain (XSS). The page template stays what the panel operator installed; it must read the three variables.
**Verified live (9 Nov 2026):** apply on the test store, then the subscription page of a test user (fetched with `Accept: text/html`) showed the brand name, the support link and the logo; revert emptied `custom_variables` again. Installing the page template is an operator step on the panel (below).

## PG-12 - per-store usage report (done, 8 Nov 2026)
`GET /stores/{id}/reseller/usage-report` and the reseller bot screen / `/usage`: account counts by state, total used volume, the 5 heaviest accounts, near-expiry (3 days) and near-exhaustion (90%) counts, read from the panel for that store's own admin only. A panel that cannot answer shows "temporarily unavailable", never an old number; no IP, device or link. The daily digest still carries no usage number (`store_usage.py`).

## R7-R10 status (8 Nov 2026): DONE
R7 (stored panel numbers become dated snapshots, `online_at`/`lifetime_used_traffic` dropped), R8 (link read from the panel, `delivery_snapshot` only as the as-delivered fallback),
R9 (`sold_*` vs panel "now") and R10 (`sync.record_sale` is the only writer; syncs never copy state) are implemented and the copied columns are dropped by `0054`.
The suite (2275 tests) is green; tests that seeded usage/link/status on the account now seed them on a fake panel.

## Verification pass (9 Nov 2026)
Checked on the branch itself, not taken from the change log: backend suite, PostgreSQL lane for the mediator tests, migrations `0050` <-> `0054` on PostgreSQL 16, import-linter contracts, ruff, both web apps (tests, lint, admin build). Two real findings were fixed (layers contract; near-expiry warning confirmed by a live read, see CHANGE_LOG). Items that needed the live panel/VPS were checked in the next section (9 Nov 2026, live recheck).

## Store role name is configurable (9 Nov 2026)
`POST /admin/panels/{id}/store-role/apply {confirm_name, bootstrap, role_name?}`: `role_name` defaults to `melorin-store`; any name of 2-32 characters
(`a-z`, `0-9`, `-`, `_`) is accepted except the names the panel or Melorin already uses (`owner`, `administrator`, `operator`, `melorin-service`).
The name is checked before the panel is called. `GET .../store-role-plan?role_name=` previews the body for a name. `revert` clears `admin_role` and
`admin_role_managed`; the role itself stays on the panel (Melorin never deletes roles).

## PG-05 proven on the live test panel (9 Nov 2026)
Provision had been applied earlier; this pass ran **rotate** for real: temporary owner key (made by the operator inside the panel container, used once,
deleted, never stored) -> new key under `melorin-service` verified (`least_privilege`, no missing permission) -> switch -> old key deleted. A stray
second service key from an earlier attempt was found active and removed. The owner key `bot` (admin Ajdar) is still active on the panel: revoke it
there once nothing else uses it.

## Live proof, 9 Nov 2026 (test panel 5.6.0) - what the real panel showed that fakes did not
| Finding | Fix |
|---|---|
| Applying `melorin-store` changed nothing for admins that already existed: `sync_all` only picks unfinished/unsynced rows, and `ensure_admin` never sent `role_id` | `ensure_admin` moves an existing admin to the wanted role (never an owner); `apply`/`revert` flag the panel's rows (`profile_synced=False`) so the next sync moves them |
| Moving an admin needs the role id: the service role got `403 admin_roles.read_simple` | permission added to `CAPABILITY_REQUIREMENTS["admin_ops"]` (single source); the live service role was updated by a rotate |
| Rotate sometimes failed with `422 Password must contain at least one special character` (the service admin's throw-away password was `token_urlsafe(32)`) | `generate_password() + generate_password()` (meets the panel rule) |
| Panel backup with `MELORIN_PANEL_BACKUP_PATHS` failed: `privkey.pem` is `root:0600`, the worker runs as uid 10001 | operator step: `setfacl` (below). The database-only backup had been fine |

Result on the test panel: `ml_main` holds `melorin-store`; rotate repeats cleanly (old key deleted); key list is `bot` (owner, still to be revoked by the operator) + the current service key.

### Branding, end to end
1. Operator installs the page once: copy `infra/sub-template/index.html` to `<CUSTOM_TEMPLATES_DIRECTORY>/subscription/index.html`, set `CUSTOM_TEMPLATES_DIRECTORY=/var/lib/pasarguard/templates/` and `SUBSCRIPTION_PAGE_TEMPLATE=subscription/index.html` in the panel's `.env`, `docker compose up -d pasarguard`.
2. Store owner saves the three fields; admin calls `.../sub-branding/{panel_id}/apply {confirm_name}`; Melorin writes `custom_variables` and reads them back.
3. A subscription link opened with `Accept: text/html` shows the brand. (From the server itself use the panel's own port, e.g. `https://127.0.0.1:8000/sub/<token>`; the public domain may not loop back.)

### Panel backup, operator steps
`MELORIN_PANEL_BACKUP_DATABASE_URL` (real database port, not PgBouncer) and `MELORIN_PANEL_BACKUP_PATHS=/panel-data`; mount `/var/lib/pasarguard:/panel-data:ro` into the worker (`docker-compose.override.yml`, which also joins the panel's backend network); give the worker's uid read access to the cert key so it can be archived:
`setfacl -m u:10001:rx /var/lib/pasarguard/certs /var/lib/pasarguard/certs/<domain>; setfacl -m u:10001:r .../privkey.pem; setfacl -d -m u:10001:r .../<domain>` (default ACL so a renewed key inherits it). Then run `scripts/verify_panel_backup.sh` with the age identity. On a production host the identity must NOT live on the server (on this test host it does).

## Live recheck, 9 Nov 2026 (test VPS, branch head `b4886e3`, all through MCP)
| Item | Result |
|---|---|
| Code | `ruff check` clean; backend suite `2325 passed, 2 skipped, 12 deselected` (`-m "not integration and not concurrency"`, 11 min); server migrations at the current head (see `docs/STATUS.md`). |
| PG-05 provision/rotate | Melorin runs on API key `melorin-service-b5ad7d` (admin `melorin-service`, role `melorin-service`, 1470 requests and rising). The owner key `bot` (admin Ajdar) is **idle** (request count unchanged over 50 s, 9409) and is still active: revoking it is the operator's decision. |
| `melorin-store` role | Panel admin `ml_main` holds `melorin-store`; `panels.config.admin_role=melorin-store`, `admin_role_managed=true`; `panel_admins` row `active`, `profile_synced=true`. The role name is configurable per panel (`role_name`), so a store or panel may use another name. |
| Subscription branding | The vetted page template on the panel is byte-identical to `infra/sub-template/index.html`; panel `.env` has `CUSTOM_TEMPLATES_DIRECTORY` and `SUBSCRIPTION_PAGE_TEMPLATE`. `ml_main.custom_variables` is currently `[]` (reverted after the 9 Nov end-to-end proof; not re-applied in this pass). |
| Prometheus | `secrets/metrics-token` is `65534:65534 0600`, container user `nobody`; target `melorin-api` **up**, 21 rules loaded, `melorin_panel_nodes` returns data, `MelorinPanelDegraded` firing (4 nodes in certificate error: operator step). |
| `MELORIN_PANEL_BACKUP_*` | `..._DATABASE_URL` (real port, not PgBouncer) and `..._PATHS=/panel-data` are set in the worker; `docker-compose.override.yml` mounts `/var/lib/pasarguard` read-only. `backup_runs`: scheduled panel backups at 02:40 `succeeded` (encrypted, verified, local only); the two `failed` rows are the manual runs made before the ACL fix. |
| Open (operator) | Revoke owner key `bot`; rotate the Telegram token in `notification_settings`; fix node certificates (`server_ca`); Caddy `unhealthy`. N10 deferred by decision. |

## Not done yet (in priority order)

1. N10 internal-network exception (deferred by decision 8; not needed now).
2. Operator only: revoke the old owner API key `bot` on the panel once nothing else uses it; rotate the Telegram token in `notification_settings`; fix node certificates (`server_ca`); Caddy healthcheck (container `unhealthy`, runc exec error).
3. Production: keep the age identity offline; run `verify_panel_backup.sh` monthly.

## Merge note (8 Nov 2026)
`feat/pasarguard-phase6-mediator` and `feat/pasarguard-mediator-rework` were unified on this branch. The rework branch was the
superset (R1 PanelLiveView, R2, R3, L4, retention days, one additive migration). From phase6 only the `link_existing` issue action
(PG-04, for `missing_on_panel`) and the `orphans_manual` count in the reconciliation summary were added.
