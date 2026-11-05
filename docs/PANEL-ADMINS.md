# PasarGuard: one admin (Operator) per store

Every store gets its **own PasarGuard admin with role `operator`** on every enabled PasarGuard panel:

| Store | Admin username |
|---|---|
| Main Store | `ml_main` |
| Reseller store | `rs_<slug>` (e.g. `rs_ab12cd34`) |

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

## Credentials
The admin password is generated, stored encrypted and never returned by list endpoints. `GET /admin/panel-admins/{id}/credentials` (audited) shows it to
the Melorin admin; `POST .../reset-password` rotates it.
