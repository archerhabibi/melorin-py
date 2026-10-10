# مدل دامنه و داده Melorin
این مدل مفهومی است؛ DDL نهایی پس از تأیید تصمیم‌های باز ساخته می‌شود.
## Identity & Stores
`User`; `Identity` (Telegram/Google/Email, provider subject, verified_at); `Store` (Main/Reseller); `StoreMembership`/`CustomerAccount`; `ResellerProfile` (approval, debt limit, bot config); `ApiCredential` (scopes/status/rotation/revoke); `TermsAcceptance`.
## Catalog & Pricing
`Product`, `Category/Collection`, `StoreProductAvailability`, `StorePrice` (Main/Reseller/Customer Price, per-Store Currency and validity), `PricingSnapshot`, `Coupon`, `CouponRedemption`, `CouponScope`, `CouponUsageLimit`. Coupon fields include creator type/id, store scope, allowed domain, start/end, global/per-customer quota, eligible amount, max discount, combinability and status. V1 combinability defaults to false.
## Finance
`Wallet` (unique by user + store + currency); `LedgerTransaction`; `LedgerEntry`; `Payment`; `PaymentAttempt`; `Refund`; `Commission`; `CommissionRule` (per plan, Admin-configured); `CommissionReversal`; `ManualWalletAdjustment`; `StorePaymentConfiguration`. Payment/top-up belongs to one Store; purchases are wallet-funded only. Ledger append-only و مرجع حقیقت است؛ balance فقط projection/cache. مبالغ integer در کوچک‌ترین واحد canonical و Currency صریح.
## Orders & VPN
`Order`, `OrderItem`, `OrderStateTransition`, `VpnAccount`, `ProvisioningAttempt`, `Server`, `Panel`, `PanelAccountSnapshot`, `ReconciliationIssue`.
## Other
`ReferralRelationship`, `ReferralReward`, `CommissionRule`, `TestAccountPolicy`, `TestAccountGrant`, `Ticket`, `TicketMessage`, `TicketAttachment`, `Notification`, `NotificationDeliveryAttempt`, `TelegramEventDestination`, `AuditEvent`, `OutboxEvent`, `IdempotencyRecord`, `FeatureFlag`, `SystemSetting`, `MaintenanceRule`, `FileObject`.
## قیود
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
