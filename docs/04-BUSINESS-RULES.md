# قواعد کسب‌وکار / Business Rules

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** قواعد کسب‌وکار، وضعیت‌ها و محدودیت‌ها.



## English section

**Purpose:** Business rules, states, constraints and invariants.



## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `04-BUSINESS-RULES.md`

#### طراحی فنی Melorin
##### Stack
Python/FastAPI، Pydantic، SQLAlchemy 2، Alembic، PostgreSQL، Redis، ARQ، Next.js/React/TypeScript، aiogram 3، Docker Compose، OpenAPI و CI/CD. نسخه دقیق dependencyها در lockfile و ADR ثبت شود.
##### ساختار مخزن
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
##### لایه‌های Backend
1. API/Presentation: validation، authentication، StoreContext.
2. Application Services: هماهنگی Use Caseها.
3. Domain: pricing، Debt Limit، Ledger، Order State Machine، Account Lifecycle.
4. Repository: دسترسی کنترل‌شده به داده.
5. Infrastructure Adapters: Panel، Payment، Telegram، Storage، Jobs.
6. Cross-cutting: Audit، Correlation ID، Idempotency، Security، Metrics.
##### Panel Adapter
Interface: `health_check`, `capabilities`, `create_account`, `get_account`, `suspend_account`, `resume_account`, `extend_account`, `revoke_account`, `normalize_status`. خطاها transient/permanent/unknown شوند. Sanaei و PasarGuard هرکدام Contract Tests مستقل دارند.

**Capability model (PG-00).** `Capabilities` carries the four original flags plus opt-in flags (`subscription_rotate`, `node_ops`, `node_control`, `usage_ops`, `device_ops`, `bulk_ops`, `admin_ops`, `settings_ops`, `event_source`), all `False` by default, so Sanaei/upstream_bot/mock need no change. Each optional flag maps to a runtime-checkable Protocol in `adapters/base.py` (`NodeOps`, `UsageOps`, `DeviceOps`, `BulkOps`, `AdminOps`, `SettingsOps`, `EventSource`, `TrafficReset`, `SubscriptionRotate`); callers use `supports(adapter, "node_ops")` / `require(...)` instead of `getattr` guesses, and a contract test fails when an adapter advertises a flag without the methods. For PasarGuard the declared set is narrowed by the connected admin's role (`GET /api/admin` -> permissions, plus `permission_overrides`): `discover_capabilities()` returns a `CapabilityReport` (effective flags, `denied` -> missing permissions, role, users scope). The snapshot lives in `panels.capabilities` (+ `capabilities_checked_at`, migration 0044); it is refreshed when a panel is created, when its connection details change, on an explicit health check, and hourly by `panel_health_job`. A failed probe never erases the last good one. `PanelOut.capabilities` exposes it to the admin UI. PasarGuard is a package (`adapters/pasarguard/{core,users,admins,nodes,events,capabilities}.py`); the old import path is unchanged.

**API contract (PG-17).** `tests/fixtures/pasarguard-openapi-5.6.0.contract.json` is the slimmed OpenAPI of the panel version the adapter targets. `tests/test_pasarguard_openapi_contract.py` drives every adapter operation against a recording panel and checks each real request (route, query parameters, JSON fields, required fields), the capability route/permission tables and the status/period enums against it. On a PasarGuard upgrade run `python scripts/pasarguard_contract.py diff <openapi.json> --fixture <fixture>`; refresh the fixture with `slim` only after the adapter is compatible.
##### Payment Adapter
`create_payment_intent`, `verify_callback`, `query_payment_status`, `refund` (در صورت پشتیبانی), `normalize_status`. Callback باید verify و deduplicate شود. کارت‌به‌کارت دستی جریان مستقل با رسید و تأیید Admin دارد.
##### Jobs
ARQ + Redis برای Provisioning/retry، expiration، near-expiration، panel health، reconciliation، notification، commission/reversal، debt checks، backup/retention، reporting و outgoing webhook delivery. هر Job idempotent، retryable، دارای backoff و قابل مشاهده باشد. Webhookها باید امضای HMAC، timestamp، replay protection، retry محدود، delivery log و امکان توقف/بازفعال‌سازی endpoint داشته باشند.
##### Wallet-first purchase and coupon rules
تمام خریدها فقط از Wallet مرتبط با Store کسر می‌شوند. Payment Adapter یک شارژ Wallet ایجاد می‌کند؛ پس از شارژ موفق، کاربر سفارش را با Wallet می‌پردازد. برای Reseller Store، روش و مقصد شارژ متعلق به همان Reseller Store است. Debit مشتری، بدهی Reseller در Main Store، Order و Ledger باید اتمیک باشند. Coupon validation، scope، سقف، تاریخ و quota فقط در Core انجام می‌شود؛ V1 ترکیب Couponها را به‌طور پیش‌فرض نمی‌پذیرد.
##### Concurrency
DB constraints و row-level locking/atomic updates برای Wallet، Debt، Coupon، Test Limit و Provisioning. Redis lock به‌تنهایی تضمین صحت مالی نیست. APIهای حساس Idempotency-Key می‌پذیرند.
##### API/Migration
Prefix `/api/v1`; OpenAPI در CI بررسی شود. Alembic migrations روی DB خالی و نسخه قبلی تست شوند. Breaking changes با versioning/deprecation مدیریت شوند. Error response نباید stack trace یا secret برگرداند.

##### بازطراحی صفحه‌های زیرساخت ادمین (پنل · سرور · بسته · محصول)

###### مسیر جدید
`پنل و سرورها ← بسته فروش (اختیاری) ← محصول`

| صفحه | تغییر |
|---|---|
| پنل‌ها + سرورها | **ادغام شد.** سرور فقط یک «ظرفیت» از یک پنل است؛ زیر همان پنل ساخته/ویرایش/فعال می‌شود. فرم «پنل جدید» هم‌زمان اولین سرور و عضویت بسته را می‌سازد. لینک‌های قدیمی `#/servers?...` به `#/panels?...` می‌روند. |
| بسته فروش | انتخاب دستی، نام‌گذاری و «در دسترس نمایندگان» به بخش پیشرفته رفت (هیچ کانالی — ربات/سایت — انتخاب دستی را به‌کار نمی‌برد؛ فقط API). محصولات بسته از خود بسته اضافه/برداشته می‌شوند. |
| محصول | «ساخت بسته جدید» داخل فرم محصول؛ کد محصول از مدت و حجم ساخته می‌شود؛ دسته‌بندی/توضیح/تست و «انتشار در فروشگاه‌ها» جمع‌شونده‌اند. محصول جدید خودکار در فروشگاه اصلی منتشر می‌شود (رفتار قبلی API). |

###### حذف / جابه‌جایی
- «محصولات مجاز» روی سرور (`product_codes`): تکراری با مسیر محصول←بسته←پنل؛ فقط در «تنظیمات پیشرفته» سرور، و نشان «فقط N محصول» در فهرست.
- نمای کارتی/جدولی پنل‌ها و صفحه‌ی جداگانه‌ی سرورها: جایگزین شد با یک نمای واحد.
- انتخاب بسته‌ها در فرم پنل قبلاً اثری نداشت (کلید `panels` که API نادیده می‌گرفت)؛ اکنون با `panel_ids` ذخیره می‌شود.
- کد مرده‌ی «انتخاب بسته‌ای» (بدون چک‌باکس) حذف شد.

###### بدون تغییر
API، دیتابیس و منطق تخصیص (`vpn/allocation.py`) دست‌نخورده‌اند.

### منبع / Source: `04-BUSINESS-RULES.md`

#### طراحی تمدید (Renewal) در هسته

> وضعیت: پیاده‌سازی‌شده در شاخه `feat/renewal-core`. وبسایت و ربات هیچ منطق تمدیدی ندارند؛ فقط پاسخ Core را نمایش می‌دهند و سفارش می‌سازند.

##### قوانین کسب‌وکار
1. **چه اکانتی تمدید می‌شود:** اکانتی که از قبل وجود دارد، متعلق به همان مشتری و همان فروشگاه است، تست/لغوشده/بایگانی/در حال ساخت نیست و از تاریخ انقضای آن **حداکثر ۱۰ روز** گذشته است (`GRACE_DAYS` در `vpn/renewal.py`). اکانتی که هنوز منقضی نشده هم قابل تمدید است. بعد از ۱۰ روز باید اکانت جدید خرید.
2. **تمدید = رفتار پکیج اولیه:** پس از تمدید، اکانت دقیقاً مثل یک اکانت تازه از همان پکیج است: انقضا = `اکنون + duration_days`، حجم = `traffic_gb` (۰ = نامحدود)، مصرف صفر. چیزی به باقی‌مانده اضافه نمی‌شود.
3. **قیمت:** قیمت **فعلی** همان محصول در **بسته فروش اولیه‌ی اکانت** (برای نماینده: قیمت خرده‌فروشی همان بسته). از کیف پول مشتری کسر می‌شود. تمدید هرگز بسته، پنل یا پکیج دیگری انتخاب نمی‌کند.

##### جریان (یکسان برای سایت و ربات)
```
GET  /stores/{id}/accounts/{acc}/renewal   -> renewable? دلیل، پکیج + قیمت فعلی، وضعیت پس از تمدید، مهلت
POST /stores/{id}/checkout/quote           (vpn_account_id)  -> همان قوانین + بخش renewal
POST /stores/{id}/orders  kind=renewal     -> orders.create_order
        renewal.check_renewable  (مالکیت، پنجره ۱۰ روز، بدون تمدید در حال انجام؛ قفل ردیف اکانت)
        پکیج باید همان پکیج اکانت باشد
        allocation.plan_sale(kind="renewal")  (بسته اولیه + قیمت فعلی؛ قیمت‌نخورده در فروشگاه نماینده = رد، نه رایگان)
        کسر کیف پول + سفارش در یک تراکنش
worker -> vpn.provision_order -> renewal.apply_to_panel
        extend(expire=now+duration, limit=package GB)  سپس reset_traffic
        (پنل بدون reset: limit = مصرف‌شده + حجم پکیج؛ نتیجه برای مشتری همان است)
```
`GET /stores/{id}/vpn-accounts` فیلدهای `can_renew` و `renew_until` را هم می‌دهد تا دکمه فقط در پنجره مجاز دیده شود.

##### نکات ایمنی
- **Idempotent:** مقادیر مطلق‌اند؛ تلاش مجدد پس از خطا دوبار چیزی اضافه نمی‌کند (قبلاً تلاش مجدد حجم را دوباره اضافه می‌کرد).
- **Timeout:** در تمدید، «اکانت روی پنل هست» دلیل موفقیت نیست؛ فقط اگر پنل زمان/حجم جدید را نشان دهد (`renewal.landed`) موفق ثبت می‌شود، وگرنه تلاش مجدد و در نهایت بازگشت وجه خودکار.
- **تمدید همزمان:** تا پایان یک تمدید باز، تمدید دوم (حتی با کلید Idempotency دیگر) با `RENEWAL_IN_PROGRESS` رد می‌شود.
- **بازگشت وجه:** مثل قبل مقدار قبلی انقضا/حجم برگردانده می‌شود (`vpn.renewal_rollback`)؛ مصرف ریست‌شده قابل بازگرداندن نیست.

##### کدهای خطا (409)
`ACCOUNT_NOT_RENEWABLE`, `RENEWAL_WINDOW_PASSED`, `RENEWAL_IN_PROGRESS`, `RENEWAL_PRODUCT_MISMATCH`, `RENEWAL_PRODUCT_UNAVAILABLE`, `RENEWAL_NOT_PRICED`

##### استعلام اکانت (Inquiry) — طراحی یکسان در ربات و سایت
- **یک منبع قانون:** `vpn/inquiry.py`. مشتری فقط اکانت‌های خودش در همین فروشگاه (`user_id` و `store_id` هر دو همیشه در کوئری؛ جزئیات: `05-SYSTEM-ARCHITECTURE.md`)، صاحب فروشگاه نماینده فقط اکانت‌های همان فروشگاه (`store_id` همیشه در کوئری). ربات و سایت فقط نمایش می‌دهند؛ ارقام (روز مانده، مصرف) از Core و Core از پنل VPN می‌گیرد (`POST .../refresh`، حداکثر هر ۱۵ ثانیه برای هر اکانت).
- **ربات اصلی و نماینده (`runner.py`):** لیست صفحه‌ای ۸تایی + چیپ‌های همه/فعال/رو‌به‌اتمام/منقضی با شمارنده + جستجو (یک‌بار مصرف) + کارت زنده (رفرش از پنل، QR، تمدید). در ربات نماینده، صاحب فروشگاه `/allaccounts` (یا «مدیریت ← اکانت‌های مشتریان») را دارد؛ Core برای غیرصاحب ۴۰۳ می‌دهد.
- **سایت:** یک کامپوننت `AccountInquiry.jsx` هم برای «اکانت‌های VPN» مشتری و هم تب «اکانت‌های مشتریان» پنل نماینده (جستجوی زنده، چیپ‌ها، صفحه‌بندی، دکمه بروزرسانی از پنل).
- **مالک پلتفرم (ادمین):** `GET /admin/vpn-accounts` هم جستجو (نام اکانت/نام یا ایمیل مشتری)، فیلتر فروشگاه و وضعیت و صفحه‌بندی دارد؛ در پنل ادمین بخش «اکانت‌های VPN» جستجوی زنده دارد.

##### قانون دید و تمدید (نماینده / کاربر عادی)
- **کاربر عادی:** هم در فهرست و هم در جستجو فقط اکانت‌های خودش در همین فروشگاه (`user_id` و `store_id` همیشه در کوئری؛ اکانتی که در فروشگاه/ربات دیگر خریده دیده و تمدید نمی‌شود).
- **نماینده:** *فهرست* فقط اکانت‌هایی است که خودش در همین فروشگاه ساخته (`user_id = خودش` و `store_id = همین فروشگاه`)؛ *جستجو* (نام اکانت، نام یا ایمیل مشتری) علاوه بر آن، اکانت‌های مشتریان **همان فروشگاه خودش** را هم پیدا می‌کند (`store_id` همیشه در کوئری؛ مشتریان نماینده‌ی دیگر دیده نمی‌شوند و ۴۰۴ می‌گیرند). شمارنده‌ی چیپ‌ها روی همان دامنه‌ی فهرست (اکانت‌های خودش) است.
- **تمدید توسط نماینده:** `GET .../reseller/accounts/{id}/renewal` و `POST .../reseller/accounts/{id}/renew` (هدر `Idempotency-Key`). فقط برای اکانت خودش یا مشتریان فروشگاه خودش؛ همان قوانین Core (مهلت ۱۰ روز، همان پکیج، قیمت فعلی، یک تمدید باز). سفارش به نام صاحب اکانت ثبت می‌شود و **از کیف پول صاحب اکانت در همان فروشگاه** کسر می‌شود (نماینده می‌تواند کیف پول مشتری را شارژ کند)؛ تمدید مشتری در audit با `order.renewed_by_owner` و شناسه‌ی نماینده ثبت می‌شود.

##### همه‌ی عملیات در Core (ربات و سایت فقط نمایش می‌دهند)
- **یک لایه‌ی سرویس:** `vpn/inquiry.py` — `customer_accounts/summary`، `reseller_accounts/summary/find`، `admin_accounts`، `reseller_renewal_offer`، `reseller_renew`. روترها (`vpn`, `reseller`, `admin`) فقط پارامترها را می‌گیرند و همین توابع را صدا می‌زنند.
- **متن‌های قانون را Core می‌دهد:** `renew_note` (چرا قابل تمدید نیست، مثلاً مهلت ۱۰ روز)، `holder_label` (اکانت خودتان / مشتری: …)، `note` در summary نماینده (فهرست فقط اکانت‌های خودش است)، `payer_note` در پیشنهاد تمدید نماینده (از کیف پول چه کسی کسر می‌شود). ربات و سایت هیچ‌کدام این قانون‌ها یا متن‌ها را خودشان نمی‌نویسند.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
