# معماری Melorin
**تصمیم:** Modular Monolith در V1؛ Microservices از ابتدا استفاده نمی‌شود. امکان اجرای چند Instance و جداسازی آینده حفظ می‌شود.

```text
Website / Admin / Main Bot / Reseller Bots / Reseller API / WebApp
                         | REST/OpenAPI
                      FastAPI Core
                         |
 Identity/Stores | Catalog/Pricing | Wallet/Ledger | Payment
 Orders | VPN Accounts | Provisioning | Referral | Tickets
 Notifications/Events | Audit/Security | Reporting/Config
                         |
                PostgreSQL / Redis / Workers
                         |
 Store-scoped Payment Adapters / Sanaei / PasarGuard / Telegram / Webhook Delivery / Storage
```
## اصول
- Core تنها مالک Business Logic و دسترسی مستقیم DB است.
- Channelها فقط UI/API clients هستند.
- StoreContext در تمام Use Caseهای Store-scoped اجباری است.
- Domain Events و Outbox برای انتشار مطمئن رویدادها.
- DB transaction برای تغییرات داخلی؛ شبکه/Panel/Gateway داخل transaction طولانی اجرا نشود.
- عملیات خارجی با State Machine، Retry، Idempotency و Compensation.
- Adapter مستقل برای Panel، Gateway، Telegram و Storage؛ تنظیمات Gateway و مقصد پرداخت در StoreContext نگهداری می‌شوند.
- تمام خریدها از Wallet همان Store کسر می‌شوند؛ Gateway فقط شارژ Wallet را تأمین می‌کند.
- نماینده پیش‌شرط عضویت فعال در Main Store دارد و فقط مشتریان عضو Store خودش را مدیریت می‌کند.
- ARQ + Redis برای صف کارهای پس‌زمینه.
- Outgoing Webhook از V1 با امضا، replay protection، retry و delivery log.
- Redis برای cache/coordination/queue، نه مرجع مالی.
- API تا حد امکان stateless؛ worker و scheduler جدا.
## ماژول‌ها
Identity & Linking; Stores/Resellers; Authorization; Catalog; Pricing/Discount; Wallet/Ledger; Payment; Order; VPN Account; Server/Panel Registry; Provisioning/Reconciliation; Referral/Commission; Test Account; Ticket; Notification/Outbox; Audit/Security; Reporting/Search; Storage; Configuration/Feature Flags; Operations/Health.
## Events
`OrderCreated`, `PaymentSucceeded`, `WalletCredited`, `WalletDebited`, `ProvisioningStarted`, `ProvisioningCompleted`, `ProvisioningFailed`, `RefundCompleted`, `CustomerLinked`, `ResellerDebtLimitReached`.
V1 از Event Dispatcher داخلی و Outbox table استفاده کند؛ Broker مستقل فقط در صورت نیاز واقعی.
## تصمیم‌های باز
Nginx/Caddy، Sentry یا جایگزین، Local/S3-compatible، JWT/session، Monitoring/Log stack و Email authentication. ARQ + Redis تصمیم قطعی است.
