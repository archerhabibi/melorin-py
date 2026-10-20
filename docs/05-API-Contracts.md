# قرارداد API — Melorin
## اصول
REST/JSON، `/api/v1`، OpenAPI، Authorization در Core، StoreContext سمت سرور، rate limiting، audit و idempotency. پاسخ عملیاتی دارای `request_id` یا `correlation_id` باشد.
## Endpoint groups
- `/auth/*`, `/me`, `/me/identities`, `/me/stores`
- `/stores/{store_id}/catalog`, `/products`, `/pricing`
- `/checkout/quote`, `/orders`, `/orders/{id}` (همه زیر `/stores/{store_id}/`)
- `/payments/intents`, `/payments/{id}`, `/payments/callbacks/{provider}` (store-scoped wallet top-up only)
- `/stores/{store_id}/wallet`, `/stores/{store_id}/wallet/topups`, `/stores/{store_id}/wallet/transactions`
- `/stores/{store_id}/coupons`, `/stores/{store_id}/coupons/validate`, `/stores/{store_id}/coupons/redemptions`
- `/wallet`, `/wallet/transactions`, `/wallet/topups`
- `/stores/{store_id}/vpn-accounts`, `/vpn-accounts/{id}/suspend`, `/resume`, `/renew`
- `/reseller/applications` (domain + bot token optional at filing), `/reseller/applications/{id}/details` (domain + bot token after approval, status `awaiting_details`), `/reseller/applications/{id}/cancel`, `/reseller/customers`, `/reseller/reports`
- `/tickets`, `/tickets/{id}/messages`, `/attachments`
- `/admin/stores`, `/admin/resellers`, `/admin/products`, `/admin/servers`, `/admin/panels`
- `/admin/orders`, `/admin/payments`, `/admin/refunds`, `/admin/ledger`
- `/admin/settings`, `/admin/feature-flags`, `/admin/audit`, `/admin/health`
## Error
```json
{"error":{"code":"ORDER_PROVISIONING_FAILED","message":"سفارش نیازمند بررسی است.","correlation_id":"..."}}
```
کد خطا پایدار باشد؛ stack trace و secret افشا نشود.
## Pagination/Webhooks
Pagination با سقف page size، filter/sort whitelist و exportهای سنگین به Job. Outgoing Webhook در V1 پیاده‌سازی می‌شود: endpointهای مجاز و event subscriptions، HMAC signature، timestamp، replay protection، retry/backoff، delivery log، timeout و امکان disable. Payload نباید secret یا داده شخصی غیرضروری داشته باشد.
## Wallet-first checkout and Coupon
`checkout/quote` باید Store، موجودی Wallet، قیمت و Coupon را در Core اعتبارسنجی کند. خرید فقط با Wallet همان Store نهایی می‌شود؛ پرداخت مستقیم درگاه برای سفارش وجود ندارد و درگاه فقط Wallet را شارژ می‌کند. Reseller فقط Couponهای Store خودش را مدیریت می‌کند؛ Admin می‌تواند دامنه مجاز بیشتری تعریف کند. Channel حق اعتبارسنجی نهایی یا محاسبه مستقل تخفیف را ندارد.
## Reseller API
Credential lifecycle: Create, Activate, Disable, Rotate, Revoke. Scopes، store isolation، audit و rate limit الزامی. Reseller API در V1 پیاده‌سازی و فعال است؛ Admin بتواند API هر Reseller را غیرفعال کند. Secret خام فقط هنگام ایجاد نمایش داده شود.
