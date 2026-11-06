# PasarGuard: one admin (Operator) per store

Every store gets its **own PasarGuard admin with role `operator`** on every enabled PasarGuard panel:

| Store | Admin username |
|---|---|
| Main Store | `ml_main` |
| Reseller store | `rs_<slug>` (e.g. `rs_ab12cd34`) |

If that name is already held by ANOTHER store on the same panel (two slugs that collapse to one name, or a login that was taken
first), the store gets the same name with a slice of its store id (`rs_ab_cd_1a2b3c`, always <= 34 chars). Two stores never share one panel login.

All accounts sold through a store (the reseller's own and their customers') are created under that store's admin. The Main
Store sells its own customers' accounts from `ml_main`, separately from every reseller.

## When an admin is created
* a new reseller store appears, a new PasarGuard panel is added (immediately), or a reseller that existed before the panel meets it:
  the worker's `panel_admin_sync_job` (every minute) plans and creates the missing admins; `POST /admin/panel-admins/sync` does it now;
* provisioning also creates it lazily; if the admin cannot be made ready the order is retried (never created under the wrong admin);
* accounts that already existed are moved under their store's admin once (`adopted`).

Opt out per panel with `config.admin_per_store = false`. Role name can be changed with `config.admin_role` (default `operator`).

## Account ownership
`AccountSpec.owner` -> after `POST /api/user` Melorin calls `PUT /api/user/by-id/{id}/set_owner?admin_username=...`. Renewals, suspend,
delete and traffic reset keep using the panel's owner credential (they work on any user).

## Profile & contact (optional, admin only)
`profile_title`, `support_url`, `telegram_id`, `discord_webhook`, `sub_domain`, `note`. Defaults are empty. Only the Melorin admin edits them:
`PATCH /admin/panel-admins/profile {store_id, panel_id?, profile}`.
A reseller cannot edit: `GET /stores/{id}/reseller/panel-admin` (read-only) and
`POST /stores/{id}/reseller/panel-admin/change-requests {changes, message}` (`profile_title`, `support_url`, `telegram_id`, `discord_webhook`; one pending
request per store). The admin reviews: `GET /admin/panel-admin-requests`, `POST .../{id}/apply {changes?, note}` (may edit before applying) or
`POST .../{id}/reject`. A push the panel refuses is kept (`profile_synced=false`) and retried by the worker.

## Guarantees (enforced by the database, not only by code)
| Guarantee | How |
|---|---|
| One admin per (panel, store) | unique `(panel_id, store_id)` |
| One panel login belongs to one store | unique `(panel_id, username)` (migration `0041`); `pick_username` avoids clashes before they reach the database |
| The worker and provisioning can race for a row | each INSERT runs in its own SAVEPOINT; the loser re-reads the winner's row (no crash, no duplicate) |
| One pending change request per store | partial unique index on `store_id WHERE status = 'pending'`; the route answers `REQUEST_PENDING` (409) |
| Database and panel never disagree for good after a password reset | the new secret is saved and flagged first, the panel is updated second, a clean refusal restores the old secret, a crash converges through the worker's next sync |

Migration `0041` refuses to run (listing the names) if two stores already share a panel login: that needs a human decision. Older duplicate
*pending* requests are cancelled, newest kept. The concurrency guarantees are proven on PostgreSQL (`tests/test_panel_admins_postgres.py`, lane `TEST_PG_URL`).

## Credentials
The admin password is generated, stored encrypted and never returned by list endpoints. `GET /admin/panel-admins/{id}/credentials` (audited) shows it to
the Melorin admin; `POST .../reset-password` rotates it (two-phase, see Guarantees; a panel that refuses leaves the old password in place and answers 502).
