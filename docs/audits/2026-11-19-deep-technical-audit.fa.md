# گزارش ممیزی فنی عمیق Melorin-Py

- تاریخ ممیزی: 2026-11-19
- شاخه مبنا: `main`
- commit مبنا: `e9d99082427fa322c23d1fb4221598421790111c`
- شاخه گزارش: `audit/deep-technical-review-2026-11-19`
- وضعیت: ممیزی ایستا و بازبینی شواهد CI؛ بدون تغییر در کد اجرایی

## 1. خلاصه مدیریتی

Melorin-Py یک Modular Monolith نسبتاً بالغ است، نه یک سرویس کوچک: API مبتنی بر FastAPI، دو وب‌اپ، دو runner تلگرام، worker/outbox، اتصال به پنل‌های VPN، پرداخت، کیف پول، گزارش‌گیری و زیرساخت Docker/CI را در یک مخزن نگه می‌دارد.

نقاط قوت معماری و امنیتی قابل مشاهده‌اند: جداسازی StoreScope، ledger دوطرفه و append-only، کلیدهای idempotency، قفل ردیف‌های مالی، outbox مبتنی بر PostgreSQL، کنترل دسترسی نقش‌محور، TOTP برای ادمین، rate limit با fail-closed در محیط میزبانی‌شده، نگهداری access token وب در حافظه و refresh token در cookie با HttpOnly، کنترل SSRF و pin کردن DNS برای webhookها، imageهای digest-pinned و اجرای containerها با کاربر غیر root و capability محدود.

با این حال، ممیزی مسیرهای پرداخت و عملیات، سه نقص مشخص را نشان داد که پیش از اتکا به چرخه‌های مالی باید اصلاح شوند. علاوه بر آن، استقرار فعلی روی main در مرحلهٔ بررسی SSH شکست خورده و شواهد واقعی چند integration و restore هنوز در اسناد پروژه «تأییدنشده» ثبت شده‌اند.

**نتیجه:** از نظر طراحی پایه و کنترل‌های دفاعی، وضعیت امیدوارکننده است؛ اما این بررسی به‌تنهایی تأییدیهٔ آمادگی Production نیست. اولویت اصلاح باید به ترتیب: ایجاد پرداخت، امکان بازپرداخت، تکمیل پیکربندی refund زرین‌پال، و سپس رفع موانع CI/Deploy و تکمیل شواهد محیط واقعی باشد.

## 2. دامنه و روش

بازبینی شامل موارد زیر بود:

- metadata، commit مبنا، درخت کامل Git و ساختار برنامه؛
- معماری API و مرزهای Core/Domain/Kernel/Modules؛
- احراز هویت، مجوزها، StoreScope، rate limit، رمزنگاری، logging و proxy trust؛
- پرداخت، callback، کیف پول، ledger، order payment و refund؛
- worker، outbox، webhook و storage؛
- رابط تنظیمات پرداخت در Admin Web و transport مشترک API؛
- Dockerfileها، Compose، Caddy و workflowهای GitHub Actions؛
- مستندات کیفیت، بدهی فنی، وضعیت انتشار و شواهد تست.

این ممیزی از طریق سورس و metadata عمومی GitHub انجام شد. اجرای مستقل کل تست‌ها در محیط محلی این نشست، اتصال به Production، مشاهدهٔ secretها، اجرای تراکنش واقعی در زرین‌پال، دسترسی به پنل‌های Sanaei/PasarGuard و انجام restore واقعی در دسترس نبود. بنابراین هرجا شواهد عملیاتی لازم است، مورد به‌عنوان «نیازمند اعتبارسنجی محیط واقعی» مشخص شده است.

## 3. نمای معماری و خط مبنا

بر اساس فایل تولیدشدهٔ `docs/STATUS.md`:

| شاخص | مقدار ثبت‌شده |
|---|---:|
| ORM tables | 82 |
| API operations | 439 |
| API paths | 391 |
| Test files | 251 |
| Test functions (static count) | 2,223 |
| Alembic migrations | 1 baseline migration |

درخت مخزن در زمان ممیزی 1,264 مسیر داشت. سند کیفیت پروژه، اجرای 2,711 تست API و 12 مورد skip را برای 2026-11-16 گزارش می‌کند. همچنین `TODO.md` نتیجهٔ load probe در 2026-11-18 را 74 rps، p95 برابر 984ms و صفر خطا ثبت کرده است. این اعداد **شواهد ثبت‌شده در اسناد پروژه‌اند، نه اجرای مجدد مستقل در این ممیزی**.

### نقاط قوت تأییدشده در سورس

1. **جداسازی tenant/store:** `StoreScope` جفت `user_id + store_id` را در query و lock اعمال می‌کند و برای رکورد خارج از scope پاسخ مشابه not-found می‌دهد.
2. **صحت مالی:** ledger با postings متوازن، ثبت transaction و entries جداگانه، کلید یکتای idempotency و قفل walletها پیاده شده است.
3. **پرداخت تکراری:** `mark_succeeded` ردیف Payment را lock می‌کند و با کلید ledger از دوباره‌اعتباردهی جلوگیری می‌کند.
4. **بازپرداخت crash-safe:** RefundOperation، lease و ثبت نتیجهٔ gateway پیش از reversal دفترکل، و recovery برای وضعیت نامعلوم وجود دارد.
5. **امنیت نشست:** access token در حافظهٔ مرورگر است؛ refresh token در cookie غیرقابل‌خواندن از JavaScript نگهداری می‌شود. احراز هویت ادمین علاوه بر نقش، session کانال ادمین و TOTP را بررسی می‌کند.
6. **مقاومت زیرساخت:** Docker imageها با digest ثابت شده‌اند؛ API و botها non-root هستند؛ در Compose برای سرویس‌ها cap_drop، محدودیت منابع و در سرویس‌های مناسب read-only filesystem دیده می‌شود.
7. **خروجی‌های ناامن:** webhookها HTTPS را الزام می‌کنند، IPهای خصوصی را رد می‌کنند، DNS را resolve و IP انتخابی را برای اتصال pin می‌کنند و redirect را دنبال نمی‌کنند.

## 4. یافته‌های ممیزی

شدت‌ها:
- **P0:** خطر فوری و بحرانی امنیتی/مالی.
- **P1:** نقص مهم در مسیر اصلی کسب‌وکار یا عملیات Production.
- **P2:** نقص جدی با workaround یا اثر محدودتر.
- **P3:** بهبود کیفیت، نگهداری یا hardening.

### AUD-001 — Retry ایجاد پرداخت با همان idempotency key پاسخ غیرقابل استفاده می‌دهد

- شدت: **P1**
- حوزه: Payments / Idempotency
- وضعیت: **تأییدشده از روی کد**
- شواهد:
  - `apps/api/melorin/modules/payments/service.py:84-90` رکورد موجود را بدون بررسی وضعیت یا `external_operation` برمی‌گرداند.
  - `apps/api/melorin/modules/payments/service.py:130-138` در خطای gateway، Payment را با وضعیت `pending` و `meta.external_operation = create_failed` commit می‌کند و سپس exception را بالا می‌فرستد.
  - `apps/api/tests/service/test_payments_service_db.py:154-165` فقط ثبت خطا و re-raise را تست می‌کند؛ retry با همان کلید بررسی نشده است.

**سناریوی بازتولید:** درخواست اول با کلید K یک Payment می‌سازد؛ فراخوانی gateway خطا می‌دهد؛ Payment در DB با وضعیت pending و بدون external_ref/instructions باقی می‌ماند. درخواست دوم با همان K از ابتدای تابع همان Payment را برمی‌گرداند، `instructions` خالی می‌دهد و gateway را دوباره فراخوانی نمی‌کند.

**اثر:** کاربر می‌تواند در وضعیت pending گیر کند و هیچ لینک پرداختی نگیرد. اگر خطا ناشی از timeout پس از پذیرش درخواست توسط درگاه باشد، نتیجهٔ بیرونی نامعلوم می‌ماند؛ تلاش مجدد با کلید جدید نیز ممکن است intent دوم در درگاه بسازد.

**پیشنهاد اصلاح:**
- برای intent creation یک state machine صریح تعریف شود: `creating / created / failed / unknown`.
- خطای قطعی provider از timeout/نتیجهٔ نامعلوم تفکیک شود.
- در حالت قطعی، Payment نباید به‌صورت pending بدون دستورالعمل به مشتری برگردد.
- در حالت نامعلوم، recovery/reconciliation یا idempotency سمت provider لازم است؛ ساخت intent دوم بدون بررسی وضعیت قبلی مجاز نباشد.
- تست DB برای retry با همان کلید، timeout پس از پذیرش درگاه، و پاسخ ناموفق قطعی اضافه شود.

### AUD-002 — غیرفعال کردن درگاه می‌تواند بازپرداخت پرداخت موفق را مسدود کند

- شدت: **P1**
- حوزه: Payments / Refund / Operations
- وضعیت: **تأییدشده از روی کد**
- شواهد:
  - `apps/api/melorin/modules/payments/service.py:39-42` تنظیمات درگاه غیرفعال را با `PAYMENT_METHOD_DISABLED` رد می‌کند.
  - `apps/api/melorin/modules/payments/service.py:309-320` مسیر `_claim_refund` برای پرداخت موفق، قبل از ایجاد/claim کردن RefundOperation از `store_payment_settings` استفاده می‌کند؛ آن تابع شرط فعال بودن درگاه را اعمال می‌کند.

**اثر:** مدیر ممکن است برای توقف شارژهای جدید، درگاه را disable کند؛ اما همان تغییر می‌تواند refund تراکنش‌های موفق قبلی را نیز غیرممکن کند. این دو قابلیت باید از نظر lifecycle مستقل باشند.

**پیشنهاد اصلاح:**
- تنظیمات «ایجاد پرداخت جدید» از «اعتبارنامهٔ موردنیاز برای refund پرداخت تاریخی» جدا شود.
- غیرفعال بودن provider مانع ایجاد intent جدید باشد، اما به‌تنهایی مانع refund یک Payment موفق نشود.
- وجود credential معتبر و امکان واقعی refund جداگانه بررسی شود؛ در نبود credential، وضعیت باید به manual review روشن و قابل پیگیری برود.
- تستی اضافه شود که Payment را با provider فعال ایجاد و موفق کند، provider را disable کند و سپس رفتار refund را بررسی کند.

### AUD-003 — رابط Admin برای زرین‌پال امکان ثبت access_token لازم برای refund را ندارد

- شدت: **P2**
- حوزه: Admin Web / Zarinpal / Refund
- وضعیت: **تأییدشده از روی کد UI و adapter**
- شواهد:
  - `apps/api/melorin/modules/payments/adapters/zarinpal.py:73-82` در refund وجود `gateway.zarinpal.access_token` و authority را الزامی می‌کند.
  - `apps/admin-web/src/features/payments/PaymentParts.tsx:304-308` فرم Zarinpal فقط `merchant_id` و `sandbox` را در state نگه می‌دارد.
  - `apps/admin-web/src/features/payments/PaymentsView.tsx:168` payload ذخیره فقط `secret: { merchant_id }` می‌فرستد.
  - `apps/api/melorin/modules/payments/store_config.py:74-77` تنها access_token موجود قبلی را حفظ می‌کند؛ مسیر UI برای ثبت مقدار جدید دیده نمی‌شود.

**اثر:** پیکربندی تازه از طریق پنل می‌تواند پرداخت را با merchant_id انجام دهد، اما credential لازم برای refund خودکار را فراهم نمی‌کند. تست‌های adapter وجود access_token را در سطح adapter بررسی می‌کنند، ولی اتصال فرم Admin به این credential پوشش داده نشده است.

**پیشنهاد اصلاح:**
- فیلد write-only برای access_token به فرم اضافه شود؛ مقدار فعلی هرگز به UI بازگردانده نشود.
- ارسال مقدار خالی، secret قبلی را حفظ کند؛ جایگزینی/حذف secret رفتار صریح داشته باشد.
- تست UI/API برای ذخیره، حفظ، جایگزینی و استفاده از token در refund اضافه شود.
- با AUD-002 در یک مرحلهٔ مالی هماهنگ اصلاح شود.

### AUD-004 — چند اجرای CI مربوط به PRهای وابستگی در lock check شکست خورده‌اند

- شدت: **P2**
- حوزه: CI / Dependency management
- وضعیت: **شکست CI تأییدشده؛ علت ریشه‌ای هنوز تعیین نشده**
- شواهد:
  - اجرای CI شمارهٔ `44533704985` روی شاخهٔ Dependabot مربوط به PR #116 در job `quality` و مرحلهٔ `scripts/lock_requirements.sh --check` شکست خورده است.
  - در همان اجرا، `postgres-lane` و `web-e2e` موفق بوده‌اند.
  - مرحله‌های بعد از lock check در job کیفیت به علت شکست مرحلهٔ قبلی اجرا نشده‌اند.
  - فایل `.github/workflows/ci.yml:28-31` این check را به‌عنوان gate اجباری اجرا می‌کند.

**اثر:** به‌روزرسانی‌های وابستگی ممکن است پیش از اجرای کامل lint/type/test متوقف شوند؛ در نتیجه backlog Dependabot قابل ادغام نمی‌شود و مشخص نیست یک update واقعاً با کل quality gate سازگار است یا نه.

**پیشنهاد اصلاح:**
- خروجی کامل مرحلهٔ شکست‌خورده برای هر PR خوانده شود و diff lock تولیدشده با lock ثبت‌شده مقایسه شود.
- نسخهٔ uv و روش تولید lock در Dependabot/CI یکسان شود.
- یک workflow یا دستور واحد برای به‌روزرسانی `.in` و تولید `.txt` hash-locked تعریف شود.
- پس از اصلاح، PRهای وابستگی باز با اولویت امنیتی دوباره اجرا شوند.

### AUD-005 — Deploy روی commit فعلی main در مرحلهٔ بررسی SSH شکست خورده است

- شدت: **P1 برای آمادگی استقرار؛ خارج از اثبات باگ کد**
- حوزه: Deployment / Operations
- وضعیت: **شکست workflow تأییدشده**
- شواهد:
  - اجرای Deploy شمارهٔ `44536410368` روی commit مبنای این ممیزی (`e9d99082427fa322c23d1fb4221598421790111c`) شکست خورده است.
  - job `deploy` در step با عنوان `Check the deploy configuration and SSH reachability` متوقف شده است؛ job آماده‌سازی موفق بوده و job ساخت image اجرا نشده است.

**اثر:** از وضعیت فعلی نمی‌توان نتیجه گرفت که commit جاری روی سرور Production مستقر شده است. این شکست لزوماً باگ برنامه نیست و به SSH host/key/secrets/network یا تنظیمات deploy مربوط می‌شود.

**پیشنهاد اصلاح:**
- لاگ همان run و secret names (بدون افشای مقدار secret) بررسی شود.
- hostname، port، fingerprint/known_hosts، user و کلید deploy در GitHub Environment/Secrets تطبیق داده شود.
- پس از رفع، deploy مجدد و health check، migration check و smoke test کنترل‌شده ثبت شود.

### AUD-006 — تعدادی از integrationها و تمرین بازیابی هنوز شواهد محیط واقعی ندارند

- شدت: **P1 به‌عنوان release gate**
- حوزه: Integrations / Disaster recovery
- وضعیت: **در اسناد پروژه به‌صراحت تأییدنشده**
- شواهد: `docs/21-ROADMAP-TECHNICAL-DEBT.md:15-16` موارد زیر را `Not verifiable here` ثبت می‌کند:
  - پنل واقعی PasarGuard/Sanaei؛
  - ربات واقعی تلگرام؛
  - زرین‌پال واقعی/sandbox؛
  - Caddy به‌همراه Prometheus؛
  - تمرین restore از S3.

**اثر:** تست mock و قرارداد adapter برای صحت ساختار کد مفیدند، اما سازگاری API provider، TLS، محدودیت‌ها، اعتبارنامه، رفتار شبکه و restore عملیاتی را ثابت نمی‌کنند.

**پیشنهاد اصلاح:**
- برای هر integration یک staging smoke test با credential محدود و گزارش تاریخ‌دار ثبت شود.
- برای S3، restore کامل روی مقصد جداگانه انجام شود؛ صرفاً وجود backup یا checksum کافی نیست.
- این موارد تا زمان ارائهٔ شواهد، release checklist باقی بمانند.

## 5. ریسک‌ها و موضوعات نیازمند بررسی تکمیلی

این موارد در این مرحله به‌عنوان باگ قطعی ثبت نشده‌اند، اما در دور بعدی باید با اجرای تست یا مشاهدهٔ محیط واقعی بررسی شوند:

1. `apps/api/melorin/worker/wrap.py` قفل job مبتنی بر Redis را در صورت نبودن Redis یا خطای Redis fail-open اجرا می‌کند. باید برای هر job مشخص شود که هم‌زمانی چند worker بی‌خطر است یا نیاز به قفل DB/رفتار fail-closed دارد.
2. در مستندات، برخی فراخوانی‌های API در Admin Web هنوز از مسیرهای پویا استفاده می‌کنند و type-check endpoint به endpoint کامل نیست؛ `TODO.md` حدود 210 call-site را گزارش می‌کند. ratchet فعلی جلوی افزایش را می‌گیرد، اما تکمیل تایپ همچنان بدهی فنی است.
3. PR #119 با عنوان `refactor(audit): pre-release r14` هنوز باز است و GitHub آن را `mergeable_state=dirty` گزارش می‌کند. قبل از شروع PRهای اصلاحی جدید باید تصمیم گرفته شود که این PR قدیمی بسته شود یا با main به‌روز و حل تعارض شود.
4. در اجرای CI شکست‌خوردهٔ Dependabot، jobهای PostgreSQL و web E2E موفق بودند؛ با این حال به علت توقف job کیفیت، نتیجهٔ کل pipeline سبز نیست.
5. تنظیمات واقعی Production، secretها، DNS، backup destination، retention و دسترسی سرور از سورس عمومی قابل اثبات نیستند.

## 6. برنامهٔ پیشنهادی اصلاح

هر ردیف باید روی Branch مستقل، با تست regression و PR جدا انجام شود:

| ترتیب | Branch پیشنهادی | محدوده |
|---|---|---|
| 1 | `fix/payments-intent-retry` | state machine و retry امن ایجاد intent، تست timeout/خطای قطعی |
| 2 | `fix/payments-refund-config` | جداسازی enable flag از credential refund و امکان ثبت write-only access_token زرین‌پال |
| 3 | `fix/ci-lock-reproducibility` | رفع ناهماهنگی lock generation و اجرای کامل quality gate روی PRهای Dependabot |
| 4 | `ops/verify-deploy-and-dr` | رفع SSH deploy و ثبت شواهد staging/provider/restore |

ترتیب فوق عمداً اولویت را به correctness مالی می‌دهد. اصلاحات مالی نباید هم‌زمان با refactorهای بزرگ UI یا ارتقای گستردهٔ dependencyها انجام شوند؛ هر PR باید کوچک، قابل بازبینی و دارای تست مستقل باشد.

## 7. معیار پذیرش قبل از ادغام هر PR

- تست regression مربوط به یافته اضافه شده و در CI اجرا شود.
- تست‌های PostgreSQL برای مسیرهای قفل/هم‌زمانی مالی سبز باشند.
- ledger balance و idempotency invariants حفظ شوند.
- هیچ migration مخرب یا حذف داده بدون طرح انتقال و rollback وارد نشود.
- قرارداد OpenAPI و client generated در صورت تغییر endpoint به‌روز باشد.
- lint، mypy، import-linter، coverage floor، frontend tests، build و Compose validation سبز باشند.
- هیچ secret یا PII به log، response یا fixture غیرمحافظت‌شده وارد نشود.
- PR فقط پس از review و green checks ادغام شود؛ هیچ commit مستقیمی به main انجام نشود.

## 8. جمع‌بندی

ممیزی کد، پایهٔ معماری و کنترل‌های دفاعی مناسبی را نشان می‌دهد؛ اما در مسیر مالی، رفتار retry ایجاد پرداخت و وابستگی refund به وضعیت فعال درگاه باید اصلاح شود. همچنین فرم زرین‌پال با نیاز credential مربوط به refund هم‌راستا نیست. در سطح عملیات، Deploy فعلی به علت SSH gate متوقف شده و شواهد چند integration و S3 restore هنوز کامل نیست.

این گزارش فقط یافته‌ها و برنامهٔ اصلاح را ثبت می‌کند. **هیچ کد اجرایی، migration، تنظیمات Production یا secretی در این مرحله تغییر داده نشده است.**


## 9. پیگیری پس از ممیزی — 2026-11-19

این بخش شواهد و وضعیت اصلاحات پس از ثبت گزارش اولیه را نگه می‌دارد؛ یافته‌های بخش 4 همچنان snapshot زمان ممیزی هستند.

### وضعیت اصلاحات کد

| یافته | PR | وضعیت فعلی |
|---|---|---|
| AUD-001 — ایجاد پرداخت و retry امن | [#130](https://github.com/archerhabibi/melorin-py/pull/130) | باز؛ state machine fail-closed، ثبت کلید idempotency در مرورگر و پوشش legacy `create_failed` اضافه شده است. تست‌های محلی پرداخت/زرین‌پال 74 و تست‌های وب فروشگاه 85 مورد موفق؛ هر سه job CI (quality، PostgreSQL، web E2E) موفق‌اند. |
| AUD-002 — refund پس از disable درگاه | [#131](https://github.com/archerhabibi/melorin-py/pull/131) | باز؛ سه job CI موفق و تست‌های ترکیبی محلی موفق. |
| AUD-003 — credential بازپرداخت زرین‌پال | [#132](https://github.com/archerhabibi/melorin-py/pull/132) | باز؛ سه job CI موفق و تست‌های Admin Web محلی موفق. |
| AUD-004 — lock/quality در Dependabot | [#116](https://github.com/archerhabibi/melorin-py/pull/116) و [#133](https://github.com/archerhabibi/melorin-py/pull/133) | در head فعلی PR #116، `scripts/lock_requirements.sh --check` موفق است؛ شکست جاری quality از قانون جدید Ruff `ASYNC240` در دو فراخوانی هم‌زمان `Path.exists/stat` در worker backup است. PR #133 آن‌ها را با `asyncio.to_thread` اصلاح می‌کند؛ 55 تست محلی و Ruff 0.17.5 موفق؛ هر سه job CI (quality، PostgreSQL، web E2E) موفق‌اند. |
 
سه شاخهٔ #130، #131 و #132 به‌صورت محلی و موقت روی main ترکیب شدند؛ تعارض ادغام نداشتند و 86 تست ترکیبی مالی/درگاه/زرین‌پال موفق شدند. این آزمایش هیچ ref راه‌دور یا main را تغییر نداد.

### شواهد عملیاتی تکمیلی

- **AUD-005:** لاگ اجرای Deploy شمارهٔ `44536410368` علت را قطعی می‌کند: هر چهار secret لازم در سطح repository موجود نبوده‌اند: `DEPLOY_HOST`، `DEPLOY_USER`، `DEPLOY_SSH_KEY` و `DEPLOY_KNOWN_HOSTS`. این شکست ناشی از secret/configuration است، نه اثبات خطای کد. مقدار هیچ secretی خوانده یا افشا نشده است. رفع آن نیازمند اقدام مالک مخزن در تنظیمات GitHub است.
- **AUD-006:** در محیط MCP بررسی‌شده، نام متغیرهای محیطی مربوط به Telegram، Zarinpal، PasarGuard/Sanaei، S3 و Deploy موجود نبود و container فعالی نیز اجرا نمی‌شد. بنابراین اجرای smoke test واقعی این providerها یا S3 restore از این محیط ممکن نبود؛ این موارد همچنان release gate هستند و نباید به‌عنوان تأییدشده علامت بخورند.

هیچ‌یک از PRهای اصلاحی در این پیگیری به main ادغام نشده‌اند و هیچ secret یا تنظیم Production تغییر نکرده است.


### یافتهٔ تکمیلی: AUD-007 — قفل worker در اختلال Redis به‌صورت fail-open عمل می‌کرد (P1)

بازبینی مجدد `melorin/worker/wrap.py` نشان داد که اگر `get_redis()` مقدار `None` برمی‌گرداند یا `SET NX EX` با خطا مواجه می‌شد، wrapper عمداً job را بدون قفل اجرا می‌کرد. این رفتار در تست `test_lock_fails_open_when_redis_breaks` نیز تثبیت شده بود. در نتیجه، در حالت نامعلوم بودن وضعیت قفل، چند replica می‌توانستند یک job زمان‌بندی‌شده را هم‌زمان اجرا کنند. این موضوع به‌ویژه برای jobهایی که با پنل‌ها، اعلان‌ها یا lifecycle حساب‌ها side effect دارند، ریسک تکرار عملیات ایجاد می‌کند.

اصلاح پیشنهادی/پیاده‌سازی‌شده در [PR #134](https://github.com/archerhabibi/melorin-py/pull/134):
- سیاست پیش‌فرض قفل به fail-closed تغییر کرده است: نبود Redis یا خطای Redis به `JobLockUnavailableError` منجر می‌شود و بدنهٔ job اجرا نمی‌شود.
- رخداد با برچسب کم‌کاردینالیتی `outcome="lock_error"` در `melorin_job_runs_total` ثبت و به ARQ بازپرتاب می‌شود.
- `poll_tick` که صریحاً `lock=False` دارد، بدون تغییر باقی می‌ماند؛ پردازش آن بر claim/lease ردیف‌های outbox تکیه دارد.
- تست‌های واحد به Redis حافظه‌ای و hermetic منتقل شده‌اند تا دیگر به Redis تصادفی روی ماشین توسعه/CI وابسته نباشند.
- تست‌های جدید هم نبود Redis و هم خطای backend را بررسی می‌کنند و تضمین می‌کنند بدنهٔ job اجرا نمی‌شود.

اعتبارسنجی محلی محدود به تست wrapper و worker backup بوده است؛ اجرای کامل suite در محیط MCP به‌دلیل خطای داخلی ابزار اجرا کامل نشد. CI کامل PR #134 مرجع نهایی اعتبارسنجی خواهد بود. هیچ تغییری در `main` اعمال نشده است.


### شواهد smoke test محلی Docker Compose

برای تکمیل AUD-006، با secretهای کاملاً موقت و فقط برای محیط آزمایش، تمام imageهای تعریف‌شده در Compose ساخته شدند. سپس یک پروژهٔ Compose ایزوله با PostgreSQL، Redis، migration، API، worker و دو وب‌اپ بالا آمد:
- migration اولیه روی PostgreSQL 16 با موفقیت اجرا شد.
- هر شش سرویس بلندمدت انتخاب‌شده به وضعیت healthy رسیدند.
- `/health/live` و `/health/ready` هر دو HTTP 200 دادند؛ readiness اتصال PostgreSQL و Redis، rate-limit هماهنگ و heartbeat worker را تأیید کرد.
- OpenAPI با 391 مسیر و 205 schema در دسترس بود.
- heartbeat در Redis ثبت شده بود و هر دو وب‌اپ صفحهٔ اصلی را سرو کردند.
- پس از آزمایش، containerها، network و volumeهای پروژهٔ آزمایشی حذف شدند؛ هیچ داده یا volume آزمایشی باقی نماند.

این smoke test، اجرای providerهای واقعی (Telegram، Zarinpal، PasarGuard/Sanaei) یا off-site S3 backup/restore را تأیید نمی‌کند؛ این release gateها همچنان باز هستند.


### تست‌های عملیاتی آفلاین

دو تست عملیاتی مخزن نیز مستقیماً روی محیط MCP اجرا شدند:
- `bash scripts/test_deploy.sh`: هر 10 سناریو موفق؛ شامل deploy موفق، rollback پس از health/migration failure، abort در backup failure، رد working tree دست‌کاری‌شده، اجرای streamed از طریق `bash -s`، registry pull/fallback و rollback تگ.
- `bash scripts/test_restore_drill.sh`: هر 3 سناریو موفق؛ انتخاب جدیدترین backup، پذیرش مسیر checksum خارجی، رد archive دست‌کاری‌شده و تشخیص backup خارج از RPO.

این‌ها تست‌های آفلاین/شبیه‌سازی‌شده‌اند و جایگزین restore واقعی از backup رمزنگاری‌شده در مقصد مستقل یا deploy روی host Production نیستند.


وضعیت CI پس از پیگیری: PRهای #130، #131، #132 و #133 همگی هر سه job را با موفقیت گذرانده‌اند. PR #134 نیز هر سه job (quality، PostgreSQL، web E2E) را با موفقیت گذرانده است.


### یافتهٔ تکمیلی: AUD-008 — متریک‌های worker به Prometheus نمی‌رسیدند (P1)

رجیستری `melorin.core.metrics` در حافظهٔ هر process جداگانه است. API مسیر `/metrics` را ارائه می‌کرد و تنها target در `infra/prometheus.yml` نیز `api:8000` بود؛ در حالی که ARQ worker در container/process جدا اجرا می‌شود. بنابراین counterهای `melorin_job_runs_total`، `melorin_job_item_failures_total` و histogramهای wrapper در worker ثبت می‌شدند اما Prometheus آن‌ها را scrape نمی‌کرد. در نتیجه alert موجود `MelorinJobItemFailures` عملاً ورودی worker را نمی‌دید و lock failure نیز سیگنال مانیتورینگ نداشت.

اصلاح در [PR #135](https://github.com/archerhabibi/melorin-py/pull/135):
- یک HTTP scrape endpoint کوچک در processهای background یعنی ARQ worker و scheduler بکاپ روی `:8001/metrics` اضافه شده؛ بدون publish کردن port روی host و فقط در شبکهٔ داخلی Compose.
- endpoint با همان `MELORIN_METRICS_TOKEN` احراز هویت Bearer می‌کند؛ در production نبود token به 503 منجر می‌شود و token اشتباه 401 می‌گیرد.
- startup/shutdown مربوط به ARQ و lifecycle مربوط به scheduler بکاپ endpointها را مدیریت می‌کنند.
- Prometheus دو target مستقل `melorin-worker` و `melorin-backup` را scrape می‌کند؛ `honor_labels` برچسب نام job واقعی را حفظ می‌کند.
- alert بحرانی `MelorinWorkerJobLockUnavailable` برای `outcome="lock_error"` و alertهای مجزا برای از دسترس خارج شدن endpointهای worker و backup اضافه شده‌اند.
- تست‌ها احراز هویت، مسیر توسعه، نبود token در production، lifecycle و پیکربندی scrape/alert را می‌پوشانند.

اعتبارسنجی محلی: 19 تست مرتبط worker/metrics/backup موفق؛ Ruff، Mypy و format check موفق؛ `promtool check config` و `promtool check rules` موفق (25 rule). image مربوط به API با Docker ساخته شد. در Compose ایزوله نیز PostgreSQL، Redis، API، worker، backup، Alertmanager و Prometheus همگی healthy شدند؛ Prometheus هر دو target worker و backup را up دید، متریک `poll_tick` را دریافت کرد و alert مربوط به قفل را بارگذاری کرد؛ هر دو endpoint داخلی HTTP 200 دادند. پس از تست، containerها و volumeها حذف شدند. CI کامل PR #135 هنوز باید بررسی شود.


وضعیت CI برای PR #135: run مربوط به head نهایی پس از آخرین تغییرات در صف اجراست؛ تست‌های محلی و promtool روی نسخهٔ نهایی مجدداً موفق شدند.
