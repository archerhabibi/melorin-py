# API reference

Core routes live under `/api/v1`; every response carries `X-Request-ID` and errors carry a
`correlation_id`. The route tables at the bottom are **generated from the code**
(`python scripts/gen_docs.py`) and checked in CI - do not edit between the markers. Behaviour that
a table cannot express is kept in the notes below; the high-level contract is
`docs/05-API-Contracts.md`. (This file replaces the former `API-ROUTES-ACTIVE.md` and
`API-IMPLEMENTATION.md`, whose hand-written route lists drifted from the code.)

## Behavioural notes

- Website login via Telegram bot (`docs/TELEGRAM-WEB-LOGIN.md`): browser `POST /api/v1/auth/telegram/web/sessions`, `POST …/sessions/{id}/poll`, `POST …/sessions/{id}/cancel`; bot runner (`X-Bot-Secret`) `POST …/web/bot/inspect`, `POST …/web/bot/decide`.
- Catalog: `GET /api/v1/stores/main`, `GET /api/v1/stores/by-slug/{slug}`, `GET /api/v1/stores/{store_id}`, `GET /api/v1/stores/{store_id}/catalog`.
- Checkout: `POST /api/v1/stores/{store_id}/checkout/quote`, `POST /api/v1/stores/{store_id}/orders`, `GET /api/v1/stores/{store_id}/orders/{order_id}`.
- Wallet/payment: `GET /api/v1/stores/{store_id}/wallet`, `POST /api/v1/stores/{store_id}/wallet/topups`, `GET /api/v1/stores/{store_id}/payments/{payment_id}`, `GET|POST /api/v1/payments/callbacks/{provider}` (server-to-server, global).
- Support: `POST|GET /api/v1/stores/{store_id}/tickets`, `GET|PATCH /api/v1/tickets/{ticket_id}` (customer edit: subject, priority, close/re-open), `GET|POST /api/v1/tickets/{ticket_id}/messages`, `PATCH /api/v1/tickets/{ticket_id}/messages/{message_id}` (author edit, stamped with `edited_at`).
- Admin ticket desk: `GET /api/v1/admin/tickets?status=&priority=&store_id=&q=`, `GET|PATCH /api/v1/admin/tickets/{ticket_id}`, `POST /api/v1/admin/tickets/{ticket_id}/messages` (`internal: true` = staff-only note, no customer notification), `PATCH /api/v1/admin/tickets/{ticket_id}/messages/{message_id}`.
- Admin: `/api/v1/admin/products`, `/panels`, `/servers`, `/payments`, `/orders`, `/orders/{order_id}/refund`, `/reports/summary`, `/reports/orders.csv`, `/audit`.
- Admin safe delete: `DELETE /api/v1/admin/products/{id}`, `/panels/{id}`, `/servers/{id}`, `/bundles/{id}`. Unused rows are removed (a panel takes its empty servers and group memberships with it); anything with orders/accounts, or still referenced (server product list, coupon scope, commission rule, a product's default group, the last panel of a manual group) answers `409` with a Persian reason, and the admin disables it instead. The remote VPN panel is never contacted. Audited as `*.deleted`.
- Reseller pricing (owner of the reseller store only): `GET /api/v1/stores/{store_id}/reseller/prices` (per product: store-wide `customer_price`, `cost_floor` and `bundles[]` = cost, own price, charged price, `source`, `state` per sales bundle), `PUT …/reseller/prices/{product_id}` (store-wide price), `PUT …/reseller/bundles/{bundle_id}/prices/{product_id}` (price of one package in ONE bundle; null/0 removes it and the bundle falls back to the store-wide price), `POST …/reseller/prices/batch` (many edits, `bundle_id: null` = store-wide price, all or nothing, returns the fresh table; a refusal is `422 PRICES_INVALID` with `details.errors[]`). A price below the reseller price of THAT bundle is refused (`CUSTOMER_PRICE_BELOW_COST`); the store-wide price must cover every bundle selling the package.
- Reseller wallet correction is Store-scoped, uses the Store currency, and cannot drive a customer wallet below zero.

Some SRS surface area remains intentionally behind adapters/jobs: Telegram delivery, storage S3 adapter, scheduled backup executor, outgoing webhooks, and full report exports. The domain and outbox boundaries are already present so these can be added without changing business rules.

## v1.1 additions

- `POST /stores/{store_id}/checkout/quote` returns the Core quote plus current wallet balance. `POST /stores/{store_id}/orders` accepts `payment_method=wallet` only.
- `POST /stores/{store_id}/wallet/topups` is the only external payment flow. Payment destination and gateway configuration are owned by that Store, including reseller Stores.
- Coupon endpoints: `GET/POST /stores/{store_id}/coupons`, `PATCH /stores/{store_id}/coupons/{coupon_id}`, `POST /stores/{store_id}/coupons/validate`, and redemption reporting. Admin endpoints are under `/admin/coupons`.
- Reseller API: `/reseller-api/v1/stores/{store_id}/catalog`, `customers`, `orders`, `reports`, and customer wallet adjustments. Authentication uses a Store-isolated `X-API-Key` with scopes; the key is bound to its store by Core (`core.channel.api_channel`, docs/16 §3-ب), which also enforces the key's IP allowlist and refuses suspended stores.
- Outgoing webhook management is under `/stores/{store_id}/reseller/webhooks`. Events are HMAC-signed with a timestamp and event ID, replay-safe, retried with backoff, and recorded in delivery logs.
- Worker entrypoint is `arq melorin.worker.arq_app.WorkerSettings`; the legacy `python -m melorin.worker.runner` loop remains available for local recovery.

## Routes (generated)

<!-- BEGIN GENERATED ROUTES (scripts/gen_docs.py) -->

### `admin` (92)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/admin/audit` | Audit Log |
| GET | `/api/v1/admin/bot-store-bindings` | List Bot Store Bindings |
| POST | `/api/v1/admin/bot-store-bindings` | Create Bot Store Binding |
| GET | `/api/v1/admin/broadcasts` | History |
| POST | `/api/v1/admin/broadcasts` | Send |
| GET | `/api/v1/admin/broadcasts/audiences` | Audiences |
| GET | `/api/v1/admin/bundle-products/unassigned` | Unassigned Products |
| GET | `/api/v1/admin/bundles` | List Bundles |
| POST | `/api/v1/admin/bundles` | Create Bundle |
| PATCH | `/api/v1/admin/bundles/{bundle_id}` | Update Bundle |
| DELETE | `/api/v1/admin/bundles/{bundle_id}` | Delete Bundle |
| GET | `/api/v1/admin/bundles/{bundle_id}/products` | List Bundle Products |
| PUT | `/api/v1/admin/bundles/{bundle_id}/products/{product_id}` | Set Bundle Product |
| DELETE | `/api/v1/admin/bundles/{bundle_id}/products/{product_id}` | Remove Bundle Product |
| PUT | `/api/v1/admin/bundles/{bundle_id}/stores/{store_id}` | Set Bundle Store |
| GET | `/api/v1/admin/coupons` | List Coupons |
| POST | `/api/v1/admin/coupons` | Create Admin Coupon |
| PATCH | `/api/v1/admin/coupons/{coupon_id}` | Patch Admin Coupon |
| GET | `/api/v1/admin/dashboard` | Dashboard |
| GET | `/api/v1/admin/event-center` | Admin Get |
| PUT | `/api/v1/admin/event-center` | Admin Put |
| DELETE | `/api/v1/admin/event-center` | Admin Delete |
| POST | `/api/v1/admin/event-center/check` | Admin Check |
| POST | `/api/v1/admin/event-center/provision` | Admin Provision |
| POST | `/api/v1/admin/event-center/test` | Admin Test |
| GET | `/api/v1/admin/feature-flags` | List Flags |
| PUT | `/api/v1/admin/feature-flags/{key}` | Update Flag |
| GET | `/api/v1/admin/health` | Health |
| GET | `/api/v1/admin/identity-link-reviews` | Identity Link Reviews |
| POST | `/api/v1/admin/identity-link-reviews/{review_id}/dismiss` | Dismiss Identity Review |
| POST | `/api/v1/admin/identity-link-reviews/{review_id}/reopen` | Reopen Identity Review |
| GET | `/api/v1/admin/manual-tasks` | List Tasks |
| POST | `/api/v1/admin/manual-tasks/{task_id}/done` | Mark Done |
| POST | `/api/v1/admin/manual-tasks/{task_id}/reopen` | Reopen |
| GET | `/api/v1/admin/operations/backups` | Backup Status |
| GET | `/api/v1/admin/orders` | Orders |
| POST | `/api/v1/admin/orders/{order_id}/attach-account` | Attach Account |
| POST | `/api/v1/admin/orders/{order_id}/manual-review` | Review Order |
| POST | `/api/v1/admin/orders/{order_id}/refund` | Refund Order |
| POST | `/api/v1/admin/orders/{order_id}/retry` | Retry Order |
| GET | `/api/v1/admin/panels` | Panels |
| POST | `/api/v1/admin/panels` | Create Panel |
| PATCH | `/api/v1/admin/panels/{panel_id}` | Update Panel |
| DELETE | `/api/v1/admin/panels/{panel_id}` | Delete Panel |
| POST | `/api/v1/admin/panels/{panel_id}/health` | Panel Health |
| POST | `/api/v1/admin/panels/{panel_id}/state` | Set Panel State |
| GET | `/api/v1/admin/payments` | Payments |
| GET | `/api/v1/admin/payments/{payment_id}/receipt` | Payment Receipt |
| POST | `/api/v1/admin/payments/{payment_id}/refund` | Refund Payment |
| POST | `/api/v1/admin/payments/{payment_id}/review` | Review Payment |
| GET | `/api/v1/admin/products` | List Products |
| POST | `/api/v1/admin/products` | Create Product |
| PATCH | `/api/v1/admin/products/{product_id}` | Update Product |
| DELETE | `/api/v1/admin/products/{product_id}` | Delete Product |
| GET | `/api/v1/admin/products/{product_id}/availability` | Get Availability |
| POST | `/api/v1/admin/products/{product_id}/availability` | Set Availability |
| GET | `/api/v1/admin/reports/analytics` | Report Analytics |
| GET | `/api/v1/admin/reports/analytics.csv` | Export Analytics |
| GET | `/api/v1/admin/reports/orders.csv` | Export Orders |
| GET | `/api/v1/admin/reports/summary` | Report Summary |
| GET | `/api/v1/admin/reports/timeseries` | Report Timeseries |
| GET | `/api/v1/admin/reseller-applications` | Applications |
| POST | `/api/v1/admin/reseller-applications/{application_id}/review` | Review Application |
| POST | `/api/v1/admin/reseller-applications/{application_id}/verify-bot` | Verify Application Bot |
| PUT | `/api/v1/admin/reseller-stores/{store_id}/api` | Toggle Reseller Api |
| GET | `/api/v1/admin/servers` | Servers |
| POST | `/api/v1/admin/servers` | Create Server |
| PATCH | `/api/v1/admin/servers/{server_id}` | Update Server |
| DELETE | `/api/v1/admin/servers/{server_id}` | Delete Server |
| POST | `/api/v1/admin/servers/{server_id}/state` | Set Server State |
| GET | `/api/v1/admin/settings` | Settings |
| PUT | `/api/v1/admin/settings/{key}` | Update Setting |
| GET | `/api/v1/admin/stores` | Stores |
| GET | `/api/v1/admin/stores/{store_id}/bank-sms` | Bank Sms Overview |
| POST | `/api/v1/admin/stores/{store_id}/bank-sms/reconcile` | Bank Sms Reconcile |
| PUT | `/api/v1/admin/stores/{store_id}/bank-sms/source` | Bank Sms Save Source |
| POST | `/api/v1/admin/stores/{store_id}/bank-sms/token` | Bank Sms Rotate Token |
| POST | `/api/v1/admin/stores/{store_id}/bank-sms/{sms_id}/ignore` | Bank Sms Ignore |
| POST | `/api/v1/admin/stores/{store_id}/bank-sms/{sms_id}/link` | Bank Sms Link |
| GET | `/api/v1/admin/stores/{store_id}/receipt-review` | Receipt Review Queue |
| PUT | `/api/v1/admin/stores/{store_id}/receipt-review/settings` | Receipt Review Settings |
| POST | `/api/v1/admin/stores/{store_id}/receipt-review/{payment_id}` | Receipt Review Resolve |
| GET | `/api/v1/admin/stores/{store_id}/reseller-prices` | Reseller Store Prices |
| GET | `/api/v1/admin/tickets` | Tickets |
| POST | `/api/v1/admin/tickets/attachments` | Ticket Upload Attachment |
| GET | `/api/v1/admin/tickets/{ticket_id}` | Ticket Detail |
| PATCH | `/api/v1/admin/tickets/{ticket_id}` | Update Ticket |
| POST | `/api/v1/admin/tickets/{ticket_id}/messages` | Ticket Reply |
| PATCH | `/api/v1/admin/tickets/{ticket_id}/messages/{message_id}` | Ticket Edit Message |
| GET | `/api/v1/admin/tickets/{ticket_id}/messages/{message_id}/attachment` | Ticket Message Attachment |
| GET | `/api/v1/admin/users` | Users |
| GET | `/api/v1/admin/vpn-accounts` | Vpn Accounts |

### `admin-integrations` (13)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/admin/integrations` | Get Integrations |
| PUT | `/api/v1/admin/integrations/admin-access` | Update Admin Access |
| PUT | `/api/v1/admin/integrations/backup-s3` | Update Backup S3 |
| POST | `/api/v1/admin/integrations/backup-s3/test` | Test Backup S3 |
| PUT | `/api/v1/admin/integrations/email` | Update Email |
| POST | `/api/v1/admin/integrations/email/test` | Test Email |
| PUT | `/api/v1/admin/integrations/google` | Update Google |
| POST | `/api/v1/admin/integrations/google/test` | Test Google |
| PUT | `/api/v1/admin/integrations/receipt-ocr` | Update Receipt Ocr |
| POST | `/api/v1/admin/integrations/receipt-ocr/test` | Test Receipt Ocr |
| PUT | `/api/v1/admin/integrations/telegram` | Update Telegram |
| PUT | `/api/v1/admin/integrations/telegram/main-bot-username` | Set Main Bot Username |
| POST | `/api/v1/admin/integrations/telegram/test` | Test Telegram |

### `admin-resellers` (6)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/admin/resellers` | List Resellers |
| GET | `/api/v1/admin/resellers/{store_id}` | Get Reseller |
| PATCH | `/api/v1/admin/resellers/{store_id}` | Edit Reseller |
| PUT | `/api/v1/admin/resellers/{store_id}/bot-token` | Set Bot Token |
| DELETE | `/api/v1/admin/resellers/{store_id}/bot-token` | Clear Bot Token |
| POST | `/api/v1/admin/resellers/{store_id}/verify-bot` | Verify Store Bot |

### `auth` (21)

| Method | Path | Operation |
|---|---|---|
| POST | `/api/v1/auth/admin/password` | Change Admin Password |
| POST | `/api/v1/auth/email/request-code` | Email Request Code |
| POST | `/api/v1/auth/email/verify-code` | Email Verify Code |
| POST | `/api/v1/auth/google` | Google Login |
| GET | `/api/v1/auth/google/config` | Google Config |
| GET | `/api/v1/auth/google/nonce` | Google Nonce |
| POST | `/api/v1/auth/logout` | Logout |
| POST | `/api/v1/auth/password/login` | Password Login |
| POST | `/api/v1/auth/refresh` | Refresh |
| POST | `/api/v1/auth/telegram/bot` | Telegram Bot Login |
| GET | `/api/v1/auth/telegram/config` | Config |
| POST | `/api/v1/auth/telegram/link` | Telegram Link |
| GET | `/api/v1/auth/telegram/oidc/callback` | Callback |
| GET | `/api/v1/auth/telegram/oidc/start` | Start |
| POST | `/api/v1/auth/telegram/web/bot/decide` | Bot Decide |
| POST | `/api/v1/auth/telegram/web/bot/inspect` | Bot Inspect |
| POST | `/api/v1/auth/telegram/web/sessions` | Start |
| POST | `/api/v1/auth/telegram/web/sessions/{session_id}/cancel` | Cancel |
| POST | `/api/v1/auth/telegram/web/sessions/{session_id}/poll` | Poll |
| POST | `/api/v1/auth/telegram/webapp` | Telegram Webapp |
| POST | `/api/v1/auth/web-handoff/redeem` | Web Handoff Redeem |

### `catalog` (15)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/stores/by-domain/{domain}` | Store By Domain |
| GET | `/api/v1/stores/by-slug/{slug}` | Store By Slug |
| GET | `/api/v1/stores/main` | Get Main Store |
| GET | `/api/v1/stores/{store_id}` | Get Store |
| GET | `/api/v1/stores/{store_id}/accounts/{account_id}/renewal` | Renewal Info |
| GET | `/api/v1/stores/{store_id}/accounts/{account_id}/renewal-packages` | Renewal Packages |
| GET | `/api/v1/stores/{store_id}/bundles` | Bundles |
| GET | `/api/v1/stores/{store_id}/bundles/{bundle_id}/packages` | Bundle Packages |
| GET | `/api/v1/stores/{store_id}/catalog` | Catalog |
| POST | `/api/v1/stores/{store_id}/checkout/quote` | Checkout Quote |
| GET | `/api/v1/stores/{store_id}/coupons` | List Coupons |
| POST | `/api/v1/stores/{store_id}/coupons` | Create Coupon |
| GET | `/api/v1/stores/{store_id}/coupons/redemptions` | Coupon Redemptions |
| POST | `/api/v1/stores/{store_id}/coupons/validate` | Validate Coupon |
| PATCH | `/api/v1/stores/{store_id}/coupons/{coupon_id}` | Patch Coupon |

### `health` (3)

| Method | Path | Operation |
|---|---|---|
| GET | `/health` | Health |
| GET | `/health/live` | Live |
| GET | `/health/ready` | Ready |

### `me` (10)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/me` | Get Me |
| PATCH | `/api/v1/me` | Update Me |
| POST | `/api/v1/me/2fa/enable` | Totp Enable |
| POST | `/api/v1/me/2fa/setup` | Totp Setup |
| POST | `/api/v1/me/identities/email` | Attach Email |
| POST | `/api/v1/me/identities/google` | Attach Google |
| POST | `/api/v1/me/link-codes/telegram` | Create Telegram Link Code |
| POST | `/api/v1/me/password` | Set Password |
| GET | `/api/v1/me/stores` | My Stores |
| POST | `/api/v1/me/web-handoff` | Create Web Handoff |

### `notifications` (3)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/stores/{store_id}/notifications` | List Notifications |
| POST | `/api/v1/stores/{store_id}/notifications/read-all` | Read All |
| POST | `/api/v1/stores/{store_id}/notifications/{notification_id}/read` | Mark Read |

### `orders` (4)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/stores/{store_id}/orders` | List Orders |
| POST | `/api/v1/stores/{store_id}/orders` | Create Order |
| GET | `/api/v1/stores/{store_id}/orders/{order_id}` | Get Order |
| POST | `/api/v1/stores/{store_id}/test-account` | Test Account |

### `payments` (7)

| Method | Path | Operation |
|---|---|---|
| POST | `/api/v1/payments/bank-sms/{store_id}` | Bank Sms Webhook |
| GET | `/api/v1/payments/callbacks/{provider}` | Payment Callback Get |
| POST | `/api/v1/payments/callbacks/{provider}` | Payment Callback Post |
| GET | `/api/v1/stores/{store_id}/payments` | My Payments |
| GET | `/api/v1/stores/{store_id}/payments/{payment_id}` | Get Payment |
| POST | `/api/v1/stores/{store_id}/payments/{payment_id}/receipt` | Upload Receipt |
| POST | `/api/v1/stores/{store_id}/wallet/topups` | Topup |

### `referrals` (3)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/admin/referral-rules` | List Rules |
| PUT | `/api/v1/admin/referral-rules` | Upsert Rule |
| GET | `/api/v1/me/referrals` | My Referrals |

### `reports` (2)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/reports/payments` | Payment Totals |
| GET | `/api/v1/reports/stores/{store_id}/sales` | Store Sales |

### `reseller` (54)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/reseller/applications` | My Applications |
| POST | `/api/v1/reseller/applications` | Apply |
| POST | `/api/v1/reseller/applications/{application_id}/cancel` | Cancel Application |
| POST | `/api/v1/reseller/applications/{application_id}/details` | Submit Details |
| GET | `/api/v1/stores/{store_id}/reseller/accounts` | Store Accounts |
| GET | `/api/v1/stores/{store_id}/reseller/accounts/summary` | Store Accounts Summary |
| GET | `/api/v1/stores/{store_id}/reseller/accounts/{account_id}` | Store Account |
| GET | `/api/v1/stores/{store_id}/reseller/accounts/{account_id}/qr.png` | Store Account Qr |
| POST | `/api/v1/stores/{store_id}/reseller/accounts/{account_id}/refresh` | Store Account Refresh |
| POST | `/api/v1/stores/{store_id}/reseller/accounts/{account_id}/renew` | Store Account Renew |
| GET | `/api/v1/stores/{store_id}/reseller/accounts/{account_id}/renewal` | Store Account Renewal |
| GET | `/api/v1/stores/{store_id}/reseller/api-credentials` | List Credentials |
| POST | `/api/v1/stores/{store_id}/reseller/api-credentials` | Create Credential |
| POST | `/api/v1/stores/{store_id}/reseller/api-credentials/{cred_id}/{action}` | Credential Action |
| GET | `/api/v1/stores/{store_id}/reseller/bank-sms` | Reseller Bank Sms Overview |
| POST | `/api/v1/stores/{store_id}/reseller/bank-sms/reconcile` | Reseller Bank Sms Reconcile |
| PUT | `/api/v1/stores/{store_id}/reseller/bank-sms/source` | Reseller Bank Sms Save Source |
| POST | `/api/v1/stores/{store_id}/reseller/bank-sms/token` | Reseller Bank Sms Rotate Token |
| POST | `/api/v1/stores/{store_id}/reseller/bank-sms/{sms_id}/ignore` | Reseller Bank Sms Ignore |
| POST | `/api/v1/stores/{store_id}/reseller/bank-sms/{sms_id}/link` | Reseller Bank Sms Link |
| PATCH | `/api/v1/stores/{store_id}/reseller/branding` | Branding |
| GET | `/api/v1/stores/{store_id}/reseller/broadcasts` | Broadcasts |
| POST | `/api/v1/stores/{store_id}/reseller/broadcasts` | Send Broadcast |
| GET | `/api/v1/stores/{store_id}/reseller/bundles` | Reseller Bundles |
| PUT | `/api/v1/stores/{store_id}/reseller/bundles/{bundle_id}` | Toggle Reseller Bundle |
| PUT | `/api/v1/stores/{store_id}/reseller/bundles/{bundle_id}/prices/{product_id}` | Set Reseller Bundle Price |
| GET | `/api/v1/stores/{store_id}/reseller/customers` | Customers |
| POST | `/api/v1/stores/{store_id}/reseller/customers/{customer_id}/wallet` | Adjust Customer Wallet |
| GET | `/api/v1/stores/{store_id}/reseller/event-center` | Reseller Get |
| PUT | `/api/v1/stores/{store_id}/reseller/event-center` | Reseller Put |
| DELETE | `/api/v1/stores/{store_id}/reseller/event-center` | Reseller Delete |
| POST | `/api/v1/stores/{store_id}/reseller/event-center/check` | Reseller Check |
| POST | `/api/v1/stores/{store_id}/reseller/event-center/provision` | Reseller Provision |
| POST | `/api/v1/stores/{store_id}/reseller/event-center/test` | Reseller Test |
| GET | `/api/v1/stores/{store_id}/reseller/payment-config` | Get Payment Config |
| PUT | `/api/v1/stores/{store_id}/reseller/payment-config/{provider}` | Put Payment Config |
| GET | `/api/v1/stores/{store_id}/reseller/payments` | Store Payments |
| POST | `/api/v1/stores/{store_id}/reseller/payments/{payment_id}/review` | Review Store Payment |
| GET | `/api/v1/stores/{store_id}/reseller/prices` | Reseller Prices |
| POST | `/api/v1/stores/{store_id}/reseller/prices/batch` | Set Reseller Prices Batch |
| PUT | `/api/v1/stores/{store_id}/reseller/prices/{product_id}` | Set Reseller Price |
| GET | `/api/v1/stores/{store_id}/reseller/profile` | Profile |
| GET | `/api/v1/stores/{store_id}/reseller/receipt-review` | Reseller Receipt Review Queue |
| PUT | `/api/v1/stores/{store_id}/reseller/receipt-review/settings` | Reseller Receipt Review Settings |
| POST | `/api/v1/stores/{store_id}/reseller/receipt-review/{payment_id}` | Reseller Receipt Review Resolve |
| GET | `/api/v1/stores/{store_id}/reseller/reports` | Report |
| GET | `/api/v1/stores/{store_id}/reseller/webhooks` | List Webhooks |
| POST | `/api/v1/stores/{store_id}/reseller/webhooks` | Create Webhook |
| PATCH | `/api/v1/stores/{store_id}/reseller/webhooks/{endpoint_id}` | Patch Webhook |
| DELETE | `/api/v1/stores/{store_id}/reseller/webhooks/{endpoint_id}` | Delete Webhook |
| GET | `/api/v1/stores/{store_id}/reseller/webhooks/{endpoint_id}/deliveries` | Webhook Deliveries |
| POST | `/api/v1/stores/{store_id}/reseller/webhooks/{endpoint_id}/deliveries/{delivery_id}/redeliver` | Redeliver |
| POST | `/api/v1/stores/{store_id}/reseller/webhooks/{endpoint_id}/rotate-secret` | Rotate Webhook Secret |
| POST | `/api/v1/stores/{store_id}/reseller/webhooks/{endpoint_id}/test` | Test Webhook |

### `reseller-api` (5)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/reseller-api/v1/stores/{store_id}/catalog` | Api Catalog |
| GET | `/api/v1/reseller-api/v1/stores/{store_id}/customers` | Api Customers |
| POST | `/api/v1/reseller-api/v1/stores/{store_id}/customers/{customer_id}/wallet` | Api Customer Wallet |
| GET | `/api/v1/reseller-api/v1/stores/{store_id}/orders` | Api Orders |
| GET | `/api/v1/reseller-api/v1/stores/{store_id}/reports` | Api Reports |

### `tickets` (9)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/stores/{store_id}/tickets` | List Mine |
| POST | `/api/v1/stores/{store_id}/tickets` | Create |
| POST | `/api/v1/stores/{store_id}/tickets/attachments` | Upload Attachment |
| GET | `/api/v1/tickets/{ticket_id}` | Get Ticket |
| PATCH | `/api/v1/tickets/{ticket_id}` | Update Ticket |
| GET | `/api/v1/tickets/{ticket_id}/messages` | Messages |
| POST | `/api/v1/tickets/{ticket_id}/messages` | Add Message |
| PATCH | `/api/v1/tickets/{ticket_id}/messages/{message_id}` | Edit Message |
| GET | `/api/v1/tickets/{ticket_id}/messages/{message_id}/attachment` | Message Attachment |

### `vpn-accounts` (7)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/stores/{store_id}/vpn-accounts` | Mine |
| GET | `/api/v1/stores/{store_id}/vpn-accounts/return-rules` | Return Rules |
| GET | `/api/v1/stores/{store_id}/vpn-accounts/summary` | Summary |
| GET | `/api/v1/stores/{store_id}/vpn-accounts/{account_id}` | Get |
| GET | `/api/v1/stores/{store_id}/vpn-accounts/{account_id}/qr.png` | Qr |
| POST | `/api/v1/stores/{store_id}/vpn-accounts/{account_id}/refresh` | Refresh |
| POST | `/api/v1/stores/{store_id}/vpn-accounts/{account_id}/return` | Return Vpn Account |

### `wallet` (2)

| Method | Path | Operation |
|---|---|---|
| GET | `/api/v1/stores/{store_id}/wallet` | My Wallet |
| GET | `/api/v1/stores/{store_id}/wallet/transactions` | My Transactions |

<!-- END GENERATED ROUTES -->
