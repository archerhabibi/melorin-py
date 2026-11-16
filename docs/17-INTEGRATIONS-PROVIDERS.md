# یکپارچه‌سازی‌ها و Providerها / Integrations & Providers

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** پنل‌ها، Adapterها و سرویس‌های بیرونی.



## English section

**Purpose:** Panels, adapters and external services.



## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `17-INTEGRATIONS-PROVIDERS.md`

#### Upstream-bot adapter (`kind = upstream_bot`)

Sells accounts that are fulfilled by a **parent Telegram bot without an API**. Melorin stays the shop (wallet, ledger,
catalog, return policy); the parent bot only fulfils. A dedicated Telegram *user* session chats with the parent bot as a customer.

##### Flows (all verified on the parent bot's screenshots / video)
| Melorin action | What the adapter does in the parent bot |
|---|---|
| buy (`create_account`) | `/start` -> main-menu button "خرید اکانت" -> service -> plan (`10 گیگ یک ماهه 60,000 تومان`) -> "تایید خرید" -> delivery message (name + link) |
| live status (`get_account`) | `/start` -> "خریدهای من" -> "جستجوی اکانت" -> send the upstream name -> account screen: status, used, remaining volume, end date (Jalali, converted from Tehran time). Cached for `status_ttl` seconds (60) |
| refund (`revoke_account`, مرجوعی) | account screen -> "مرجوعی اکانت" -> "تایید میکنم" -> success message; the parent bot credits its wallet back (amount is stored) |
| renew (`extend_account`) | account screen -> "تمدید اکانت" -> options (balance message + `حجم اولیه`) -> "تمدید با حجم اولیه <price> تومان" -> confirm "تایید تمدید اکانت" -> "اکانت ... رو با موفقیت تمدید کردم" + "مبلغ ... از حسابت کم کردم". **On by default** (verified on the real screens of 24 Oct 2026); `renew.enabled=false` switches it off |

Main-menu buttons are never typed from memory: after `/start` the adapter reads the reply keyboard of the parent bot and
presses the button whose text contains the configured label, so emoji and spacing are always exact.

The parent bot names accounts itself; Melorin's username is mapped to the upstream name (Redis + `VpnAccount.panel_ref`,
re-seeded by `seed_adapter` together with the stored subscription URL).

##### Setup
1. Use a **separate** Telegram account and fund the parent bot wallet from it.
2. `python scripts/upstream_bot_login.py` -> StringSession.
3. Admin -> Panels -> **Add panel -> "Upstream Bot"** (see "Admin screen" below). Or via the API: `kind=upstream_bot`,
   `base_url=https://t.me/<parent_bot>`, credentials `{"api_id":..., "api_hash":"...", "session":"..."}`, config `{"max_price": 100000}`.
   Optional config: `service_button`, `menu_buy`, `menu_purchases`, `search_button`, `refund_button`, `refund_confirm_button`,
   `confirm_button`, `cancel_button`, `link_button`, `start_command`, `plans`, `status_ttl`, `step_timeout`, `delivery_timeout`,
   `renew {enabled, renew_button, confirm_button, cancel_button, success_words, settle_window}`.
4. Map bundles/servers to this panel as for any other panel.

##### Admin screen (Admin -> Panels)
The "Upstream Bot" kind has its own form instead of the generic URL / token fields:
- **Parent bot**: paste `@name`, `name` or any `t.me` link; the panel `base_url` is stored as `https://t.me/<name>`.
- **Credentials** (`api_id`, `api_hash`, `session`) are encrypted and never shown again. All three are replaced together; an edit that
  does not touch them ("Cancel credential change") keeps the stored session. A built-in guide explains how to get them.
- **Safety cap** (`max_price`, toman) is mandatory, with one-click presets.
- **Automatic renewal** switch (`renew.enabled`, always saved explicitly) plus its button texts, success words and `settle_window`.
- **Button texts**, **manual plans** and **timing** are optional: an empty field means the adapter default (shown as placeholder),
  so only real overrides are stored in `config`. Config keys the form does not know stay in "Advanced (JSON)" and are never dropped.
- A **live preview** shows the exact path the userbot walks in the parent bot for buy / status / refund / renew with the configured texts.
- The panel card shows the bot, the cap, renewal on/off and the number of manual plans. "Save and check health" only connects with the
  session and reads the chat; it never buys anything.

###### راهنمای فارسی صفحه‌ی ادمین
در «پنل‌ها ← افزودن پنل» نوع **ربات واسط (Upstream Bot)** را انتخاب کنید: نام کاربری یا لینک ربات والد، سه مقدار `api_id`/`api_hash`/`session`
(رمزنگاری‌شده ذخیره می‌شود و دوباره نمایش داده نمی‌شود)، و **سقف مبلغ هر خرید/تمدید** (اجباری). تمدید خودکار، متن دکمه‌ها، پلن دستی و زمان‌بندی
اختیاری‌اند؛ فیلد خالی یعنی پیش‌فرض. در ویرایش، اگر «تغییر اعتبارنامه» را نزنید session قبلی حفظ می‌شود. «پیش‌نمایش مسیر» نشان می‌دهد
اکانت تلگرام اختصاصی در ربات والد دقیقاً چه دکمه‌هایی را می‌زند. «ذخیره و بررسی سلامت» فقط اتصال را می‌سنجد و هیچ خریدی انجام نمی‌دهد.

##### Safety rules built in
- `max_price` (toman) is mandatory; the confirm prompt amount must equal the chosen plan price and be <= `max_price`, otherwise the purchase is cancelled.
- One flow at a time (Redis lock + process lock). Every flow starts with `/start`, which also clears a half-finished search.
- After the confirm click, a missing answer is `UNKNOWN`, never `TRANSIENT`. Purchases: a `pending` marker lets the retry recover the delivery instead of paying twice. Refunds: a `refund_started` marker; if the account is already gone upstream on retry, the refund is considered done. Renewals: see "Renewal rules" below.
- A retry for the same Melorin username never buys again; a refund never runs twice.

##### Refund rules and the money flow
The parent bot refunds volume accounts only, <= 3 days after purchase, <= 5 % used, at most 3 per day. These are the same numbers
as Melorin's own return policy (`vpn/returns.py`), so a return Melorin allows is normally accepted upstream. Order of events:
Melorin refunds its customer (ledger) -> outbox `vpn.revoke` -> adapter refunds upstream. If the parent bot refuses (for example
usage read differently), the adapter raises a `PERMANENT` error containing the parent bot's own reply; the outbox retries and the event
center reports it, and the upstream cost stays unrecovered until handled by hand.

##### Limits
- No suspend/resume: the parent bot does not expose them (`Capabilities.suspend=False`).
- Fragile by nature: if the parent bot changes menu texts, adjust the config; failed attempts and panel health will show it.
- Telegram may limit the user account; keep volume human-like and the account dedicated.

##### Renewal rules (verified 24 Oct 2026)
- The parent bot **restarts the package from now**: new expiry = renewal moment + 1 month, usage back to 0, volume = initial volume. Remaining days are **not** added. This is the same promise Core makes (`renewal.describe` -> `remaining_days_replaced`), so no second "raise the limit" call is needed.
- Only **"تمدید با حجم اولیه"** is automated. A request for another volume (`traffic_bytes` != the "حجم اولیه" shown by the parent bot) is `PERMANENT` before anything is paid; "تمدید و افزایش N گیگ" is not guessed because its price/volume meaning is not documented by the parent bot.
- The confirm screen prints **"مبلغ 0 تومان"** although the bot really charges the option price (balance 445,000 -> 385,000 on the recording). The adapter therefore never trusts that amount: the price is taken from the chosen button (`<= max_price`, wallet balance message `>=` price), the confirm prompt must name the same account, and only `0` or the option price is accepted on it. The real charge ("مبلغ ... از حسابت کم کردم") is stored as `renew_charged`; a different charge is logged as an error but the renewal is kept.
- After the confirm click every failure is `UNKNOWN`. A `renew_started` marker makes a retry read the account screen first: a changed expiry or "تاریخ تمدید" = done; unchanged inside `settle_window` (600 s) = `UNKNOWN` again, never a second payment; unchanged after the window = the confirm never took effect, a fresh attempt is allowed.
- Stale buttons ("زمان عملیات منقضی شده") before the confirm are `TRANSIENT`; the flow always restarts from `/start`.

### منبع / Source: `panels/PANEL-ADMINS.md`

#### PasarGuard: one admin (Operator) per store

Every store gets its **own PasarGuard admin with role `operator`** on every enabled PasarGuard panel:

| Store | Admin username |
|---|---|
| Main Store | `ml_main` |
| Reseller store | `rs_<slug>` (e.g. `rs_ab12cd34`) |

If that name is already held by ANOTHER store on the same panel (two slugs that collapse to one name, or a login that was taken
first), the store gets the same name with a slice of its store id (`rs_ab_cd_1a2b3c`, always <= 34 chars). Two stores never share one panel login.

All accounts sold through a store (the reseller's own and their customers') are created under that store's admin. The Main
Store sells its own customers' accounts from `ml_main`, separately from every reseller.

##### When an admin is created
* a new reseller store appears, a new PasarGuard panel is added (immediately), or a reseller that existed before the panel meets it:
  the worker's `panel_admin_sync_job` (every minute) plans and creates the missing admins; `POST /admin/panel-admins/sync` does it now;
* provisioning also creates it lazily; if the admin cannot be made ready the order is retried (never created under the wrong admin);
* accounts that already existed are moved under their store's admin once (`adopted`).

Opt out per panel with `config.admin_per_store = false`. Role name can be changed with `config.admin_role` (default `operator`).

##### Account ownership
`AccountSpec.owner` -> after `POST /api/user` Melorin calls `PUT /api/user/by-id/{id}/set_owner?admin_username=...`. Renewals, suspend,
delete and traffic reset keep using the panel's owner credential (they work on any user).

##### Profile & contact (optional, admin only)
`profile_title`, `support_url`, `telegram_id`, `discord_webhook`, `sub_domain`, `note`. Defaults are empty. Only the Melorin admin edits them:
`PATCH /admin/panel-admins/profile {store_id, panel_id?, profile}`.
A reseller cannot edit: `GET /stores/{id}/reseller/panel-admin` (read-only) and
`POST /stores/{id}/reseller/panel-admin/change-requests {changes, message}` (`profile_title`, `support_url`, `telegram_id`, `discord_webhook`; one pending
request per store). The admin reviews: `GET /admin/panel-admin-requests`, `POST .../{id}/apply {changes?, note}` (may edit before applying) or
`POST .../{id}/reject`. A push the panel refuses is kept (`profile_synced=false`) and retried by the worker.

##### Guarantees (enforced by the database, not only by code)
| Guarantee | How |
|---|---|
| One admin per (panel, store) | unique `(panel_id, store_id)` |
| One panel login belongs to one store | unique `(panel_id, username)` (migration `0041`); `pick_username` avoids clashes before they reach the database |
| The worker and provisioning can race for a row | each INSERT runs in its own SAVEPOINT; the loser re-reads the winner's row (no crash, no duplicate) |
| One pending change request per store | partial unique index on `store_id WHERE status = 'pending'`; the route answers `REQUEST_PENDING` (409) |
| Database and panel never disagree for good after a password reset | the new secret is saved and flagged first, the panel is updated second, a clean refusal restores the old secret, a crash converges through the worker's next sync |

Migration `0041` refuses to run (listing the names) if two stores already share a panel login: that needs a human decision. Older duplicate
*pending* requests are cancelled, newest kept. The concurrency guarantees are proven on PostgreSQL (`tests/test_panel_admins_postgres.py`, lane `TEST_PG_URL`).

##### Credentials
The admin password is generated, stored encrypted and never returned by list endpoints. `GET /admin/panel-admins/{id}/credentials` (audited) shows it to
the Melorin admin; `POST .../reset-password` rotates it (two-phase, see Guarantees; a panel that refuses leaves the old password in place and answers 502).

### منبع / Source: `panels/PANEL-MEDIATOR-REWORK.md`

#### PasarGuard mediator rework: what is done, what is next

Branch `feat/pasarguard-mediator-rework` (from `main` @ `9a4a971`). Source: `MELORIN-PASARGUARD-GAP-ANALYSIS` and `…-LIVE-VERIFICATION` (8 Nov 2026).
Rule: **Melorin is a mediator**. Used traffic, limit, expiry and status belong to the panel; Melorin reads them, it does not own a copy.

##### Done in this branch (tests: `test_mediator_rework_db.py`, `test_panel_live_view_db.py`; full suite green)

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

##### R9 / R10 + dropping the copied columns: design (8 Nov 2026, migration `0054`)

Melorin has not been released, so this is done in ONE step (no "one release without readers" waiting period): readers are moved first,
then the columns go in the same migration.

###### What a `vpn_accounts` row means afterwards
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

###### Behaviour changes
* **`sync.apply_remote` no longer copies state.** It updates `status`, `last_synced_at`, queued-plan settlement and the notices (from the reading it was given). It never writes `sold_*`.
* **`sync.record_sale(account, expires_at, traffic_bytes)`** is the single writer of the entitlement. Every Melorin act calls it with the absolute values it just applied (R10).
* **`limits_drift`** compares the panel with the *sold* entitlement and now stays visible (`limits_mismatch` auto-closes when the panel and the entitlement agree again). New issue action **`accept_panel`** rebases the entitlement on the live panel values (audited). An ignored drift is not re-opened while it is identical.
* **Returns:** `evaluate()` takes the usage as a parameter. Lists pass the live reading if they have one (otherwise the usage rule is advisory-skipped); `prepare_return` always passes the strict fresh reading, so the money decision never uses a stored number. `AccountReturn.used_bytes/limit_bytes` stay as the audit snapshot.
* **Analytics:** no stored usage sums; sold volume is summed from `sold_traffic_bytes` and labelled as sold, usage comes from each panel's monitoring snapshot.
* **`expiry_job`** selects candidates by `sold_expires_at <= now` and decides on a live read (already so since R2); on-hold accounts are recognised from the live reading, not from a stored status.

###### Order of work (each step = one commit, suite green)
1. Model + migration `0054` (rename/add/drop, no data carried: unreleased). 2. `sync`/`inquiry`/`live`/`returns` (read side). 3. Acts (provisioning, renewal, plans, bulk, account_tools, runner, recreate, admin orders) call `record_sale`. 4. Reconcile/issues (`accept_panel`), analytics, directory, subscription check, delivery. 5. Tests, docs regeneration, patch.

##### Switch-on order (staging first)

1. Deploy, run `alembic upgrade head`. `0054` renames and drops columns (Melorin is unreleased; `delivery_snapshot` is back-filled from the old link columns). Verified on PostgreSQL 16: upgrade with data, downgrade, re-upgrade, `alembic check` clean.
2. Server, once: `chown 65534:65534 /opt/melorin/secrets/metrics-token && chmod 600 …`, then `docker compose up -d --force-recreate prometheus`. Check: target `up`, 21 rules loaded, `melorin_panel_nodes` returns data.
3. Look at the customer account list (`vpn.live_view` is on by default). Panel down must show "temporarily unavailable".
4. Watch one day of `expiry_job` logs (`expiry: live read failed`), then keep it.

##### PG-05 rollout (one panel, staging first)

1. `GET /admin/panels/{id}/service-access` → read `plan` (grants / withheld) and the current level (`owner` today).
2. `POST …/service-access/provision` with `confirm_name` = the panel's name (the stored credential is used if it is owner-level, or pass `bootstrap`).
3. Check the panel page: level `least_privilege`, all capabilities still on. Then revoke the old owner key **on the panel** (Melorin does not delete it).
4. Rotation later: `POST …/rotate` with an owner `bootstrap` credential (needed because the service role cannot manage keys).
Request shapes (`AdminRoleCreate`, `APIKeyCreate`) were read from the live panel's OpenAPI 5.6.0; the role was **not** applied to the live panel from this work, so run steps 1-3 on staging first.

##### PG-04 decision 1 - assigning a manual account (DECIDED and built, 8 Nov 2026)

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

##### PG-12 - the `melorin-store` role (explicit action, 8 Nov 2026)
`POST /admin/panels/{id}/store-role/apply {confirm_name, bootstrap}` creates (or realigns) the role `melorin-store` (users create/read/update/delete + groups read; **no** `api_keys`, admins, nodes, hosts, settings) with an owner credential used for that one request and never stored, then sets `panel.config.admin_role`. New and re-synced store admins get the role (`panel_admins._push` passes it on every ensure); existing admins change on their next sync. `POST .../store-role/revert` returns to the stock role and writes nothing to the panel. Both are typed-name confirmed and audited (`panel.store_role.applied|reverted`). Nothing runs automatically (decision 3).
The page itself is a fixed base template shipped in `infra/sub-template/index.html` and installed by the panel operator (`CUSTOM_TEMPLATES_DIRECTORY` + `SUBSCRIPTION_PAGE_TEMPLATE=subscription/index.html`, restart the panel). Stores never supply HTML (XSS on the subscription domain). Verified live (9 Nov 2026): `custom_variables` reach the template as `user.admin.custom_variables` (see the branding section). Roll out on staging first: apply, resync one test store admin, do a create/renew/delete round trip, then the rest.

##### PG-12 - per-store subscription branding (9 Nov 2026)
The store owner edits three plain fields, `PUT /stores/{id}/reseller/sub-branding {display_name, support_url, logo_url}` (plain text, https links only, logo must be an image URL, no markup; stored in `stores.branding["sub"]`, no migration). Saving sends nothing to a panel.
The admin puts them on the panel with an explicit action: `GET /admin/stores/{store_id}/sub-branding/{panel_id}` (read-only: wanted vs. what the panel holds), `POST .../apply {confirm_name}` and `POST .../revert {confirm_name}` (typed panel name, audited as `panel.sub_branding.applied|reverted` with key names and a digest, never values). Apply writes exactly three keys into the store admin's `custom_variables` (`melorin_brand_name`, `melorin_support_url`, `melorin_logo_url`), keeps every other key, **reads the admin back** and restores the previous values if the panel did not keep them. Nothing runs automatically (decision 3).
Melorin never writes `sub_template` or HTML: a store-chosen template would run on the subscription domain (XSS). The page template stays what the panel operator installed; it must read the three variables.
**Verified live (9 Nov 2026):** apply on the test store, then the subscription page of a test user (fetched with `Accept: text/html`) showed the brand name, the support link and the logo; revert emptied `custom_variables` again. Installing the page template is an operator step on the panel (below).

##### PG-12 - per-store usage report (done, 8 Nov 2026)
`GET /stores/{id}/reseller/usage-report` and the reseller bot screen / `/usage`: account counts by state, total used volume, the 5 heaviest accounts, near-expiry (3 days) and near-exhaustion (90%) counts, read from the panel for that store's own admin only. A panel that cannot answer shows "temporarily unavailable", never an old number; no IP, device or link. The daily digest still carries no usage number (`store_usage.py`).

##### R7-R10 status (8 Nov 2026): DONE
R7 (stored panel numbers become dated snapshots, `online_at`/`lifetime_used_traffic` dropped), R8 (link read from the panel, `delivery_snapshot` only as the as-delivered fallback),
R9 (`sold_*` vs panel "now") and R10 (`sync.record_sale` is the only writer; syncs never copy state) are implemented and the copied columns are dropped by `0054`.
The suite (2275 tests) is green; tests that seeded usage/link/status on the account now seed them on a fake panel.

##### Verification pass (9 Nov 2026)
Checked on the branch itself, not taken from the change log: backend suite, PostgreSQL lane for the mediator tests, migrations `0050` <-> `0054` on PostgreSQL 16, import-linter contracts, ruff, both web apps (tests, lint, admin build). Two real findings were fixed (layers contract; near-expiry warning confirmed by a live read, see CHANGE_LOG). Items that needed the live panel/VPS were checked in the next section (9 Nov 2026, live recheck).

##### Store role name is configurable (9 Nov 2026)
`POST /admin/panels/{id}/store-role/apply {confirm_name, bootstrap, role_name?}`: `role_name` defaults to `melorin-store`; any name of 2-32 characters
(`a-z`, `0-9`, `-`, `_`) is accepted except the names the panel or Melorin already uses (`owner`, `administrator`, `operator`, `melorin-service`).
The name is checked before the panel is called. `GET .../store-role-plan?role_name=` previews the body for a name. `revert` clears `admin_role` and
`admin_role_managed`; the role itself stays on the panel (Melorin never deletes roles).

##### PG-05 proven on the live test panel (9 Nov 2026)
Provision had been applied earlier; this pass ran **rotate** for real: temporary owner key (made by the operator inside the panel container, used once,
deleted, never stored) -> new key under `melorin-service` verified (`least_privilege`, no missing permission) -> switch -> old key deleted. A stray
second service key from an earlier attempt was found active and removed. The owner key `bot` (admin Ajdar) is still active on the panel: revoke it
there once nothing else uses it.

##### Live proof, 9 Nov 2026 (test panel 5.6.0) - what the real panel showed that fakes did not
| Finding | Fix |
|---|---|
| Applying `melorin-store` changed nothing for admins that already existed: `sync_all` only picks unfinished/unsynced rows, and `ensure_admin` never sent `role_id` | `ensure_admin` moves an existing admin to the wanted role (never an owner); `apply`/`revert` flag the panel's rows (`profile_synced=False`) so the next sync moves them |
| Moving an admin needs the role id: the service role got `403 admin_roles.read_simple` | permission added to `CAPABILITY_REQUIREMENTS["admin_ops"]` (single source); the live service role was updated by a rotate |
| Rotate sometimes failed with `422 Password must contain at least one special character` (the service admin's throw-away password was `token_urlsafe(32)`) | `generate_password() + generate_password()` (meets the panel rule) |
| Panel backup with `MELORIN_PANEL_BACKUP_PATHS` failed: `privkey.pem` is `root:0600`, the worker runs as uid 10001 | operator step: `setfacl` (below). The database-only backup had been fine |

Result on the test panel: `ml_main` holds `melorin-store`; rotate repeats cleanly (old key deleted); key list is `bot` (owner, still to be revoked by the operator) + the current service key.

###### Branding, end to end
1. Operator installs the page once: copy `infra/sub-template/index.html` to `<CUSTOM_TEMPLATES_DIRECTORY>/subscription/index.html`, set `CUSTOM_TEMPLATES_DIRECTORY=/var/lib/pasarguard/templates/` and `SUBSCRIPTION_PAGE_TEMPLATE=subscription/index.html` in the panel's `.env`, `docker compose up -d pasarguard`.
2. Store owner saves the three fields; admin calls `.../sub-branding/{panel_id}/apply {confirm_name}`; Melorin writes `custom_variables` and reads them back.
3. A subscription link opened with `Accept: text/html` shows the brand. (From the server itself use the panel's own port, e.g. `https://127.0.0.1:8000/sub/<token>`; the public domain may not loop back.)

###### Panel backup, operator steps
`MELORIN_PANEL_BACKUP_DATABASE_URL` (real database port, not PgBouncer) and `MELORIN_PANEL_BACKUP_PATHS=/panel-data`; mount `/var/lib/pasarguard:/panel-data:ro` into the worker (`docker-compose.override.yml`, which also joins the panel's backend network); give the worker's uid read access to the cert key so it can be archived:
`setfacl -m u:10001:rx /var/lib/pasarguard/certs /var/lib/pasarguard/certs/<domain>; setfacl -m u:10001:r .../privkey.pem; setfacl -d -m u:10001:r .../<domain>` (default ACL so a renewed key inherits it). Then run `scripts/verify_panel_backup.sh` with the age identity. On a production host the identity must NOT live on the server (on this test host it does).

##### Live recheck, 9 Nov 2026 (test VPS, branch head `b4886e3`, all through MCP)
| Item | Result |
|---|---|
| Code | `ruff check` clean; backend suite `2325 passed, 2 skipped, 12 deselected` (`-m "not integration and not concurrency"`, 11 min); server migrations at the current head (see `docs/STATUS.md`). |
| PG-05 provision/rotate | Melorin runs on API key `melorin-service-b5ad7d` (admin `melorin-service`, role `melorin-service`, 1470 requests and rising). The owner key `bot` (admin Ajdar) is **idle** (request count unchanged over 50 s, 9409) and is still active: revoking it is the operator's decision. |
| `melorin-store` role | Panel admin `ml_main` holds `melorin-store`; `panels.config.admin_role=melorin-store`, `admin_role_managed=true`; `panel_admins` row `active`, `profile_synced=true`. The role name is configurable per panel (`role_name`), so a store or panel may use another name. |
| Subscription branding | The vetted page template on the panel is byte-identical to `infra/sub-template/index.html`; panel `.env` has `CUSTOM_TEMPLATES_DIRECTORY` and `SUBSCRIPTION_PAGE_TEMPLATE`. `ml_main.custom_variables` is currently `[]` (reverted after the 9 Nov end-to-end proof; not re-applied in this pass). |
| Prometheus | `secrets/metrics-token` is `65534:65534 0600`, container user `nobody`; target `melorin-api` **up**, 21 rules loaded, `melorin_panel_nodes` returns data, `MelorinPanelDegraded` firing (4 nodes in certificate error: operator step). |
| `MELORIN_PANEL_BACKUP_*` | `..._DATABASE_URL` (real port, not PgBouncer) and `..._PATHS=/panel-data` are set in the worker; `docker-compose.override.yml` mounts `/var/lib/pasarguard` read-only. `backup_runs`: scheduled panel backups at 02:40 `succeeded` (encrypted, verified, local only); the two `failed` rows are the manual runs made before the ACL fix. |
| Open (operator) | Revoke owner key `bot`; rotate the Telegram token in `notification_settings`; fix node certificates (`server_ca`); Caddy `unhealthy`. N10 deferred by decision. |

##### Not done yet (in priority order)

1. N10 internal-network exception (deferred by decision 8; not needed now).
2. Operator only: revoke the old owner API key `bot` on the panel once nothing else uses it; rotate the Telegram token in `notification_settings`; fix node certificates (`server_ca`); Caddy healthcheck (container `unhealthy`, runc exec error).
3. Production: keep the age identity offline; run `verify_panel_backup.sh` monthly.

##### Merge note (8 Nov 2026)
`feat/pasarguard-phase6-mediator` and `feat/pasarguard-mediator-rework` were unified on this branch. The rework branch was the
superset (R1 PanelLiveView, R2, R3, L4, retention days, one additive migration). From phase6 only the `link_existing` issue action
(PG-04, for `missing_on_panel`) and the `orphans_manual` count in the reconciliation summary were added.

### منبع / Source: `panels/PANEL-OPS-PHASE4.md`

#### PasarGuard Phase 4 - Operations console, bulk operations, store governance, subscription check

Covers PG-07, PG-11, PG-12 and PG-13 of `MELORIN-PASARGUARD-MANAGEMENT`. Migration: `0049_pasarguard_phase4`.
Everything is built once in the core API; the admin web only consumes it. All of it needs a Melorin admin.

##### Principles applied

* **Read-only by default, dangerous actions gated.** Node reconnect/sync, core restart and enable/disable of nodes/hosts/groups
  need a written reason; core restart also needs the core's name typed back; toggles that would remove the last working path
  need `force`. Every action is audited with actor, panel, target and reason.
* **Capability-driven.** Everything goes through adapter capabilities (`insight`, `infra_control`, `bulk_actions`,
  `admin_governance`, `subscription_probe`). Panels that lack one (Sanaei, upstream bot) never see the section.
* **Idempotent and absolute.** Bulk work never replays a relative panel call (see below).
* **Nothing is deleted** by any of this. Accounts are only disabled/enabled, reset, re-linked or extended.

##### PG-07 Panel console (`PanelsView` -> Operations tab)

| Endpoint | Purpose |
|---|---|
| `GET  /admin/panels/{id}/ops` | resources, user counts by status, online users, nodes (status, xray version, coefficient, traffic) |
| `GET  /admin/panels/{id}/ops/infra` | nodes, hosts, groups, cores with enabled state |
| `POST /admin/panels/{id}/ops/nodes/{node}/{reconnect|sync}` | `{reason}` |
| `POST /admin/panels/{id}/ops/cores/{core}/restart` | `{reason, confirm_name}` |
| `POST /admin/panels/{id}/ops/{nodes|hosts|groups}/toggle` | `{ids, disabled, reason, force}` |

##### PG-11 Bulk operations

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

##### PG-12 Store-admin governance

`GET /admin/store-admins`, `POST /admin/store-admins/refresh`, `PATCH /admin/store-admins/{id}` (traffic cap in GB or clear,
panel-admin status, `notifications_off` so the panel stops messaging resellers outside Melorin). `store_governance_job` reads
each store admin's usage/limit/limited state every ~15 minutes into the table; the admin screen shows panel usage next to
Melorin's own report so they can be reconciled.

##### PG-13 Subscription consistency

`GET|POST /admin/panels/{id}/subscription-check`: compares the panel's `subscription.url_prefix`, Melorin's `sub_base_url` and
each store admin's `sub_domain`; the POST creates a throw-away test user, compares the returned link with the expected
address, fetches `/sub/{token}/info`, and always removes the test user. Mismatches are reported, never auto-fixed. To move all
accounts to a new domain use a bulk `rotate_links` operation.

##### Operating notes / runbook

* A failed node: open Operations, read the node message (e.g. self-signed certificate), fix `server_ca` on the panel, then
  `reconnect`. Do not disable TLS verification in Melorin.
* Outage compensation: Bulk operations -> `extend_days` -> filter by group/store -> **preview** -> check count and sample ->
  type the count -> confirm. Watch progress; use *resume* if it ends `partial`.
* A stuck operation: wait for the lease (5 min) or cancel it; items already applied are never re-applied.
* A migration `0049` rollback drops the new tables and columns; no existing data is touched.

##### Tests

`tests/test_pasarguard_bulk_ops.py`, `tests/test_pasarguard_ops_governance.py`, the OpenAPI contract test (every
Phase 4 call checked against the stored PasarGuard 5.6.0 schema) and `apps/admin-web/tests/panel-phase4.test.jsx`.

### منبع / Source: `panels/PANEL-OPS-PHASE5.md`

#### PasarGuard Phase 5 - Metrics and alerts, settings drift, panel backup

Covers PG-14, PG-15 and PG-16 of `MELORIN-PASARGUARD-MANAGEMENT`. Migration: `0050_pasarguard_phase5`.
Everything is built once in the core API; the admin web (Panels -> "شاخص و پشتیبان" tab) only consumes it. All endpoints need a Melorin admin.

##### Principles applied

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

##### PG-14 Metrics and alerts

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

##### PG-15 Settings drift and lifecycle policy

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

##### PG-16 Panel backup and recovery

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

Recovery procedure: `docs/18-OPERATIONS-DEPLOYMENT-DR.md`, "Panel lost: how Melorin converges".

##### Tests

`apps/api/tests/test_pasarguard_ops_maturity.py` (gauges, absence rules, snapshot failures, drift findings and policy, backup state, auth on every
endpoint, alert-rule and script contracts, worker image clients) and `apps/admin-web/tests/panel-phase5.test.jsx`.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
