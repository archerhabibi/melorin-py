# طراحی فنی Melorin
## Stack
Python/FastAPI، Pydantic، SQLAlchemy 2، Alembic، PostgreSQL، Redis، ARQ، Next.js/React/TypeScript، aiogram 3، Docker Compose، OpenAPI و CI/CD. نسخه دقیق dependencyها در lockfile و ADR ثبت شود.
## ساختار مخزن
```text
/apps/api
/apps/admin-web
/apps/store-web
/apps/telegram-main
/apps/telegram-reseller
/packages/api-client
/infra
/docs
/tests
```
## لایه‌های Backend
1. API/Presentation: validation، authentication، StoreContext.
2. Application Services: هماهنگی Use Caseها.
3. Domain: pricing، Debt Limit، Ledger، Order State Machine، Account Lifecycle.
4. Repository: دسترسی کنترل‌شده به داده.
5. Infrastructure Adapters: Panel، Payment، Telegram، Storage، Jobs.
6. Cross-cutting: Audit، Correlation ID، Idempotency، Security، Metrics.
## Panel Adapter
Interface: `health_check`, `capabilities`, `create_account`, `get_account`, `suspend_account`, `resume_account`, `extend_account`, `revoke_account`, `normalize_status`. خطاها transient/permanent/unknown شوند. Sanaei و PasarGuard هرکدام Contract Tests مستقل دارند.
## Payment Adapter
`create_payment_intent`, `verify_callback`, `query_payment_status`, `refund` (در صورت پشتیبانی), `normalize_status`. Callback باید verify و deduplicate شود. کارت‌به‌کارت دستی جریان مستقل با رسید و تأیید Admin دارد.
## Jobs
ARQ + Redis برای Provisioning/retry، expiration، near-expiration، panel health، reconciliation، notification، commission/reversal، debt checks، backup/retention، reporting و outgoing webhook delivery. هر Job idempotent، retryable، دارای backoff و قابل مشاهده باشد. Webhookها باید امضای HMAC، timestamp، replay protection، retry محدود، delivery log و امکان توقف/بازفعال‌سازی endpoint داشته باشند.
## Wallet-first purchase and coupon rules
تمام خریدها فقط از Wallet مرتبط با Store کسر می‌شوند. Payment Adapter یک شارژ Wallet ایجاد می‌کند؛ پس از شارژ موفق، کاربر سفارش را با Wallet می‌پردازد. برای Reseller Store، روش و مقصد شارژ متعلق به همان Reseller Store است. Debit مشتری، بدهی Reseller در Main Store، Order و Ledger باید اتمیک باشند. Coupon validation، scope، سقف، تاریخ و quota فقط در Core انجام می‌شود؛ V1 ترکیب Couponها را به‌طور پیش‌فرض نمی‌پذیرد.
## Concurrency
DB constraints و row-level locking/atomic updates برای Wallet، Debt، Coupon، Test Limit و Provisioning. Redis lock به‌تنهایی تضمین صحت مالی نیست. APIهای حساس Idempotency-Key می‌پذیرند.
## API/Migration
Prefix `/api/v1`; OpenAPI در CI بررسی شود. Alembic migrations روی DB خالی و نسخه قبلی تست شوند. Breaking changes با versioning/deprecation مدیریت شوند. Error response نباید stack trace یا secret برگرداند.

## بازطراحی صفحه‌های زیرساخت ادمین (پنل · سرور · بسته · محصول)

### مسیر جدید
`پنل و سرورها ← بسته فروش (اختیاری) ← محصول`

| صفحه | تغییر |
|---|---|
| پنل‌ها + سرورها | **ادغام شد.** سرور فقط یک «ظرفیت» از یک پنل است؛ زیر همان پنل ساخته/ویرایش/فعال می‌شود. فرم «پنل جدید» هم‌زمان اولین سرور و عضویت بسته را می‌سازد. لینک‌های قدیمی `#/servers?...` به `#/panels?...` می‌روند. |
| بسته فروش | انتخاب دستی، نام‌گذاری و «در دسترس نمایندگان» به بخش پیشرفته رفت (هیچ کانالی — ربات/سایت — انتخاب دستی را به‌کار نمی‌برد؛ فقط API). محصولات بسته از خود بسته اضافه/برداشته می‌شوند. |
| محصول | «ساخت بسته جدید» داخل فرم محصول؛ کد محصول از مدت و حجم ساخته می‌شود؛ دسته‌بندی/توضیح/تست و «انتشار در فروشگاه‌ها» جمع‌شونده‌اند. محصول جدید خودکار در فروشگاه اصلی منتشر می‌شود (رفتار قبلی API). |

### حذف / جابه‌جایی
- «محصولات مجاز» روی سرور (`product_codes`): تکراری با مسیر محصول←بسته←پنل؛ فقط در «تنظیمات پیشرفته» سرور، و نشان «فقط N محصول» در فهرست.
- نمای کارتی/جدولی پنل‌ها و صفحه‌ی جداگانه‌ی سرورها: جایگزین شد با یک نمای واحد.
- انتخاب بسته‌ها در فرم پنل قبلاً اثری نداشت (کلید `panels` که API نادیده می‌گرفت)؛ اکنون با `panel_ids` ذخیره می‌شود.
- کد مرده‌ی «انتخاب بسته‌ای» (بدون چک‌باکس) حذف شد.

### بدون تغییر
API، دیتابیس و منطق تخصیص (`vpn/allocation.py`) دست‌نخورده‌اند.
