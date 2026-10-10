# API implementation map

Core routes are under `/api/v1` and emit `X-Request-ID` plus JSON errors with `correlation_id`.

| area | routes |
|---|---|
| auth | `/auth/email/*`, `/auth/password/login`, `/auth/google`, `/auth/telegram/*`, `/auth/refresh`, `/auth/logout` |
| identity | `/me`, `/me/stores`, `/me/identities/email`, `/me/link-codes/telegram`, `/me/2fa/*` |
| catalog | `/stores/{store_id}`, `/stores/{store_id}/catalog`, `/stores/{store_id}/checkout/quote` |
| finance | `/stores/{store_id}/wallet`, `/wallet/transactions`, `/stores/{store_id}/wallet/topups`, `/payments/*` |
| commerce | `/stores/{store_id}/orders`, `/stores/{store_id}/test-account`, `/orders/{id}` |
| vpn | `/vpn-accounts` |
| support | `/stores/{store_id}/tickets`, `/tickets/{id}/messages` |
| reseller | `/reseller/applications`, `/stores/{store_id}/reseller/*` |
| admin | `/admin/products`, `/admin/panels`, `/admin/servers`, `/admin/payments`, `/admin/orders`, `/admin/reseller-applications`, `/admin/feature-flags`, `/admin/settings`, `/admin/audit` |

Some SRS surface area remains intentionally behind adapters/jobs: Telegram delivery, storage S3 adapter, scheduled backup executor, outgoing webhooks, and full report exports. The domain and outbox boundaries are already present so these can be added without changing business rules.

## v1.1 additions

- `POST /stores/{store_id}/checkout/quote` returns the Core quote plus current wallet balance. `POST /stores/{store_id}/orders` accepts `payment_method=wallet` only.
- `POST /stores/{store_id}/wallet/topups` is the only external payment flow. Payment destination and gateway configuration are owned by that Store, including reseller Stores.
- Coupon endpoints: `GET/POST /stores/{store_id}/coupons`, `PATCH /stores/{store_id}/coupons/{coupon_id}`, `POST /stores/{store_id}/coupons/validate`, and redemption reporting. Admin endpoints are under `/admin/coupons`.
- Reseller API: `/reseller-api/v1/stores/{store_id}/catalog`, `customers`, `orders`, `reports`, and customer wallet adjustments. Authentication uses a Store-isolated `X-API-Key` with scopes.
- Outgoing webhook management is under `/stores/{store_id}/reseller/webhooks`. Events are HMAC-signed with a timestamp and event ID, replay-safe, retried with backoff, and recorded in delivery logs.
- Worker entrypoint is `arq melorin.worker.arq_app.WorkerSettings`; the legacy `python -m melorin.worker.runner` loop remains available for local recovery.
