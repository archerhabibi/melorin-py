# مدل داده و دامنه / Domain & Data Model

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** موجودیت‌ها، مالکیت داده و مدل Person/Account.



## English section

**Purpose:** Entities, data ownership and the Person/Account model.



## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `07-DOMAIN-DATA-MODEL.md`

#### مدل دامنه و داده Melorin
این مدل مفهومی است؛ DDL نهایی پس از تأیید تصمیم‌های باز ساخته می‌شود.
##### Identity & Stores
`User`; `Identity` (Telegram/Google/Email, provider subject, verified_at); `Store` (Main/Reseller); `StoreMembership`/`CustomerAccount`; `ResellerProfile` (approval, debt limit, bot config); `ApiCredential` (scopes/status/rotation/revoke); `TermsAcceptance`.
##### Catalog & Pricing
`Product`, `Category/Collection`, `StoreProductAvailability`, `StorePrice` (Main/Reseller/Customer Price, per-Store Currency and validity), `PricingSnapshot`, `Coupon`, `CouponRedemption`, `CouponScope`, `CouponUsageLimit`. Coupon fields include creator type/id, store scope, allowed domain, start/end, global/per-customer quota, eligible amount, max discount, combinability and status. V1 combinability defaults to false.
##### Finance
`Wallet` (unique by user + store + currency); `LedgerTransaction`; `LedgerEntry`; `Payment`; `PaymentAttempt`; `Refund`; `Commission`; `CommissionRule` (per plan, Admin-configured); `CommissionReversal`; `ManualWalletAdjustment`; `StorePaymentConfiguration`. Payment/top-up belongs to one Store; purchases are wallet-funded only. Ledger append-only و مرجع حقیقت است؛ balance فقط projection/cache. مبالغ integer در کوچک‌ترین واحد canonical و Currency صریح.
##### Orders & VPN
`Order`, `OrderItem`, `OrderStateTransition`, `VpnAccount`, `ProvisioningAttempt`, `Server`, `Panel`, `PanelAccountSnapshot`, `ReconciliationIssue`.
##### Other
`ReferralRelationship`, `ReferralReward`, `CommissionRule`, `TestAccountPolicy`, `TestAccountGrant`, `Ticket`, `TicketMessage`, `TicketAttachment`, `Notification`, `NotificationDeliveryAttempt`, `TelegramEventDestination`, `AuditEvent`, `OutboxEvent`, `IdempotencyRecord`, `FeatureFlag`, `SystemSetting`, `MaintenanceRule`, `FileObject`.
##### قیود
- Identity provider + subject یکتا.
- External payment reference و idempotency scope یکتا.
- Order snapshot پس از نهایی‌شدن تغییرناپذیر.
- داده Store-scoped دارای `store_id` یا رابطه مالکیت معتبر.
- Reseller approval requires active Main Store membership/customer relationship.
- Reseller customer wallet top-up and payment configuration are scoped to that reseller Store.
- Referral attribution is first-touch/first registered referrer and immutable after attribution.
- VPN Account ownership transfer by Admin is disallowed in V1.
- Outgoing Webhook endpoint, signing secret metadata, delivery attempt and event subscription must be modeled.
- سوابق مالی/Audit حذف فیزیکی نمی‌شوند.
- FK، soft delete/archive و indexها برای هر entity مشخص شوند.

### منبع / Source: `07-DOMAIN-DATA-MODEL.md`

#### طراحی اتصال حساب‌ها (Person / Account / Login Identity)

نگاشت روی کد موجود: Person (جدید) ← Account = `users` ← Login Identity = `identities` (+ `person_id`, `status`).
- قوانین خالص: `melorin/domain/account_linking.py`؛ سرویس: `modules/identity/account_linking/`؛ migration: `0057_person_account_linking`.
- یک تلگرام فعال برای هر Person (ایندکس یکتای جزئی)؛ Google/Email نامحدود؛ هویتِ فعالِ Person دیگر هرگز بی‌صدا جابه‌جا نمی‌شود (conflict + تأیید کاربر/ادمین).
- اتصال هویت‌ها پول جابه‌جا نمی‌کند. یکپارچه‌سازی مالی (`consolidation`) جدا، idempotent، با preflight (بدهی/پرداخت و سفارش در جریان/ریسلر مسدودکننده)، انتقال دفترکل، wallet قدیمی `consolidated` و routing در `get_wallet`. کیف پول per-store می‌ماند (ایزولاسیون فروشگاه‌ها).
- تأیید ادمین برای انتقال مالی (`identity_consolidation_auto_approve` پیش‌فرض خاموش). audit فقط‌افزودنی (trigger دیتابیس).
- API: `/identity/*` (کاربر)، `/admin/identity/*`، `/internal/identity/telegram/status` (ربات).
- UI سایت: تب «اتصال حساب‌ها» در داشبورد (`dashboard/DashboardLinking.tsx`) و بخش صفحهٔ اصلی. دکمهٔ «اتصال حساب‌های من» در منوی اصلی ربات (`cmd_link_accounts`).
- Reauth: رمز فعلی، یا کد یک‌بارمصرف ایمیل برای حساب‌های بدون رمز (`account_linking/reauth.py`)؛ حساب بدون رمز و بدون ایمیل (فقط تلگرام/Google) فقط نشست دارد و گارد «آخرین روش ورود» برقرار است.
- تست‌ها: HTTP برای reauth/unlink و یکپارچه‌سازی، تست سرویس برای ایزولاسیون فروشگاه‌ها و حساب مدیر.
- باقی‌مانده: تأیید با توکن واقعی ربات/Google، و تصمیم محصولی برای حساب‌های بدون رمز و ایمیل.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
