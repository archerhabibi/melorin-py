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
## لایه‌بندی کد (Phase 3 — با import-linter اجباری می‌شود)
جهت وابستگی همیشه رو به پایین است؛ هر قرارداد در `apps/api/pyproject.toml` تعریف شده و با `make lint` و CI اجرا می‌شود.

| لایه | مسیر | مجاز به import |
|---|---|---|
| Domain (خالص) | `melorin/domain` | هیچ‌چیز از پروژه |
| Kernel | `melorin/kernel` (مدل‌های ORM، `Base`) | فقط `domain` |
| Core (زیرساخت) | `melorin/core` | فقط `kernel` و `domain` |
| ماژول‌ها (پشتهٔ بدون دور) | `melorin/modules/*` | لایهٔ پایین‌تر از خودش: `admin` › `reports` › `reseller` › `orders/payments/identity` › `catalog/referral/tickets` › `vpn/wallet/webhooks/notifications/stores/system` |
| Channelها (Adapter) | `melorin/channels/*` (Telegram OIDC/web-login، Bot API) | هیچ‌گاه `admin`، `reseller`، `reports`، worker و نقاط ورودی |
| نقاط ورودی | `app`، `cli`، `worker` | همه |

- نیاز جدید بین دو ماژول از طریق لایهٔ پایین‌تر یا رویداد Outbox برآورده می‌شود، نه import معکوس.
- مسیر مدل‌ها `melorin.kernel.models.<context>` است؛ `melorin.models` فقط برای ثبت کامل metadata (Alembic و تست‌ها) نگه داشته شده است.
- فایل‌های بزرگ بر اساس خانوادهٔ مسیر یا مسئولیت تقسیم می‌شوند (مثلاً `modules/admin/<family>.py`، `modules/reseller/routes/`، `modules/catalog/allocation/`، `modules/identity/google.py`، `telegram-main/tgmain/handlers/`) و `router.py` فقط ریشهٔ ترکیب است.
- ترتیب هر تغییر ساختاری: رفتار ثابت، OpenAPI بدون تغییر (مقایسهٔ بایت‌به‌بایت با `main`) و همهٔ تست‌ها سبز.
## Events
`OrderCreated`, `PaymentSucceeded`, `WalletCredited`, `WalletDebited`, `ProvisioningStarted`, `ProvisioningCompleted`, `ProvisioningFailed`, `RefundCompleted`, `CustomerLinked`, `ResellerDebtLimitReached`.
V1 از Event Dispatcher داخلی و Outbox table استفاده کند؛ Broker مستقل فقط در صورت نیاز واقعی.
## تصمیم‌های باز
Nginx/Caddy، Sentry یا جایگزین، Local/S3-compatible، JWT/session، Monitoring/Log stack و Email authentication. ARQ + Redis تصمیم قطعی است.
