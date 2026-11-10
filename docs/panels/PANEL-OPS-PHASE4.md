# PasarGuard Phase 4 - Operations console, bulk operations, store governance, subscription check

Covers PG-07, PG-11, PG-12 and PG-13 of `MELORIN-PASARGUARD-MANAGEMENT`. Migration: `0049_pasarguard_phase4`.
Everything is built once in the core API; the admin web only consumes it. All of it needs a Melorin admin.

## Principles applied

* **Read-only by default, dangerous actions gated.** Node reconnect/sync, core restart and enable/disable of nodes/hosts/groups
  need a written reason; core restart also needs the core's name typed back; toggles that would remove the last working path
  need `force`. Every action is audited with actor, panel, target and reason.
* **Capability-driven.** Everything goes through adapter capabilities (`insight`, `infra_control`, `bulk_actions`,
  `admin_governance`, `subscription_probe`). Panels that lack one (Sanaei, upstream bot) never see the section.
* **Idempotent and absolute.** Bulk work never replays a relative panel call (see below).
* **Nothing is deleted** by any of this. Accounts are only disabled/enabled, reset, re-linked or extended.

## PG-07 Panel console (`PanelsView` -> Operations tab)

| Endpoint | Purpose |
|---|---|
| `GET  /admin/panels/{id}/ops` | resources, user counts by status, online users, nodes (status, xray version, coefficient, traffic) |
| `GET  /admin/panels/{id}/ops/infra` | nodes, hosts, groups, cores with enabled state |
| `POST /admin/panels/{id}/ops/nodes/{node}/{reconnect|sync}` | `{reason}` |
| `POST /admin/panels/{id}/ops/cores/{core}/restart` | `{reason, confirm_name}` |
| `POST /admin/panels/{id}/ops/{nodes|hosts|groups}/toggle` | `{ids, disabled, reason, force}` |

## PG-11 Bulk operations

Kinds: `disable`, `enable`, `reset_usage`, `rotate_links` (panel bulk endpoints, idempotent) and `extend_days`, `add_traffic`
(compensation, relative).

Flow: **preview** (selection by store / group / status; freezes per-account items, sends nothing, returns count + sample,
valid 15 min) -> **confirm** (the admin must type the exact count) -> **execute** (worker, chunks of 200, ~40 s budget per run)
-> report -> **resume** after a partial run, **cancel** any time before the end.

Why a repeat is safe:

* Panel actions are idempotent, so a timeout is simply retried.
* `extend_days` / `add_traffic` never call the panel's relative bulk endpoints. Each item carries an **absolute target** computed
  at preview. At run time the panel is read first: already at target = done; still at the preview value = write the target;
  anything else = the account changed meanwhile and is **skipped**, not overwritten.
* One runner per panel (`lease_until`, 5 min); a crashed runner's lease expires by itself. Limits: 5000 accounts per operation,
  90 days, 512 GB, 5 attempts per item.

Store linkage: a reseller store has `suspend_policy` (`none` default | `disable_accounts`). With `disable_accounts`, suspending
the store plans a disable operation (and disables its panel admin) and reactivating plans the matching enable. Change it with
`PUT /admin/resellers/{store}/suspend-policy`; it applies from the next suspension.

Endpoints: `POST /admin/bulk-operations/preview`, `GET /admin/bulk-operations[/{id}]`, `POST .../{id}/confirm|cancel|resume`.
Worker: `bulk_operation_job` (every 15 s).

## PG-12 Store-admin governance

`GET /admin/store-admins`, `POST /admin/store-admins/refresh`, `PATCH /admin/store-admins/{id}` (traffic cap in GB or clear,
panel-admin status, `notifications_off` so the panel stops messaging resellers outside Melorin). `store_governance_job` reads
each store admin's usage/limit/limited state every ~15 minutes into the table; the admin screen shows panel usage next to
Melorin's own report so they can be reconciled.

## PG-13 Subscription consistency

`GET|POST /admin/panels/{id}/subscription-check`: compares the panel's `subscription.url_prefix`, Melorin's `sub_base_url` and
each store admin's `sub_domain`; the POST creates a throw-away test user, compares the returned link with the expected
address, fetches `/sub/{token}/info`, and always removes the test user. Mismatches are reported, never auto-fixed. To move all
accounts to a new domain use a bulk `rotate_links` operation.

## Operating notes / runbook

* A failed node: open Operations, read the node message (e.g. self-signed certificate), fix `server_ca` on the panel, then
  `reconnect`. Do not disable TLS verification in Melorin.
* Outage compensation: Bulk operations -> `extend_days` -> filter by group/store -> **preview** -> check count and sample ->
  type the count -> confirm. Watch progress; use *resume* if it ends `partial`.
* A stuck operation: wait for the lease (5 min) or cancel it; items already applied are never re-applied.
* A migration `0049` rollback drops the new tables and columns; no existing data is touched.

## Tests

`tests/test_pasarguard_bulk_ops.py`, `tests/test_pasarguard_ops_governance.py`, the OpenAPI contract test (every
Phase 4 call checked against the stored PasarGuard 5.6.0 schema) and `apps/admin-web/tests/panel-phase4.test.jsx`.
