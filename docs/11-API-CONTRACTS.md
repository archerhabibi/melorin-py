# قراردادهای API / API Contracts

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** قرارداد API: پیشوند `/api/v1`، گروه‌های endpoint، خطاها، pagination و webhook. OpenAPI در CI بررسی می‌شود و جزئیات مسیرها در `docs/API.md` (تولیدشده) است.

**اصول:** خطاهای پایدار با `code` و پیام امن، کلید idempotency برای عملیات مالی/اتصال، checkout wallet-first و کوپن، Reseller API با کلید نماینده. مسیرهای هویت: `/identity/link/*`، `/identity/unlink`، `/identity/consolidation`، `/identity/consolidation-status`، و احراز مجدد: `GET /identity/reauth` (روش لازم)، `POST /identity/reauth/email/start`، `POST /identity/reauth/telegram/start`؛ بدنهٔ `/identity/unlink` بسته به روش یکی از `current_password`، `reauth_code` یا `google_id_token` را می‌گیرد.

## English section

**Purpose:** the API contract: the `/api/v1` prefix, endpoint groups, errors, pagination and webhooks. OpenAPI is checked in CI and route details are in the generated `docs/API.md`.

**Principles:** stable errors with a `code` and a safe message; idempotency keys for financial/linking operations; wallet-first checkout and coupons; a Reseller API with a reseller key. Identity routes: `/identity/link/*`, `/identity/unlink`, `/identity/consolidation`, `/identity/consolidation-status`, and re-authentication: `GET /identity/reauth` (required method), `POST /identity/reauth/email/start`, `POST /identity/reauth/telegram/start`; the `/identity/unlink` body takes one of `current_password`, `reauth_code` or `google_id_token` depending on the method.

## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `11-API-CONTRACTS.md`

#### قرارداد API — Melorin
##### اصول
REST/JSON، `/api/v1`، OpenAPI، Authorization در Core، StoreContext سمت سرور، rate limiting، audit و idempotency. پاسخ عملیاتی دارای `request_id` یا `correlation_id` باشد.
##### Endpoint groups
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
##### Error
```json
{"error":{"code":"ORDER_PROVISIONING_FAILED","message":"سفارش نیازمند بررسی است.","correlation_id":"..."}}
```
کد خطا پایدار باشد؛ stack trace و secret افشا نشود.
##### Pagination/Webhooks
Pagination با سقف page size، filter/sort whitelist و exportهای سنگین به Job. Outgoing Webhook در V1 پیاده‌سازی می‌شود: endpointهای مجاز و event subscriptions، HMAC signature، timestamp، replay protection، retry/backoff، delivery log، timeout و امکان disable. Payload نباید secret یا داده شخصی غیرضروری داشته باشد.
##### Wallet-first checkout and Coupon
`checkout/quote` باید Store، موجودی Wallet، قیمت و Coupon را در Core اعتبارسنجی کند. خرید فقط با Wallet همان Store نهایی می‌شود؛ پرداخت مستقیم درگاه برای سفارش وجود ندارد و درگاه فقط Wallet را شارژ می‌کند. Reseller فقط Couponهای Store خودش را مدیریت می‌کند؛ Admin می‌تواند دامنه مجاز بیشتری تعریف کند. Channel حق اعتبارسنجی نهایی یا محاسبه مستقل تخفیف را ندارد.
##### Reseller API
Credential lifecycle: Create, Activate, Disable, Rotate, Revoke. Scopes، store isolation، audit و rate limit الزامی. Reseller API در V1 پیاده‌سازی و فعال است؛ Admin بتواند API هر Reseller را غیرفعال کند. Secret خام فقط هنگام ایجاد نمایش داده شود.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
