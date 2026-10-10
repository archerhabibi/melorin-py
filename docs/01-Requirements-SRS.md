# سند جامع نیازمندی‌ها (SRS) — Melorin
نسخه 1.1 | وضعیت: نیازمندی‌های تجمیع‌شده با تصمیم‌های مالک محصول؛ مبنای به‌روزرسانی طراحی

## 1. معرفی و هدف
Melorin پلتفرمی یکپارچه برای فروش، مدیریت و ارائه سرویس VPN از طریق فروشگاه اصلی و فروشگاه‌های نمایندگان است. تمام کانال‌ها از Core/API مرکزی و قوانین مشترک استفاده می‌کنند. مقیاس هدف 10,000 تا 100,000 کاربر، بازار اولیه ایران و زبان اصلی فارسی است.

## 2. کانال‌ها
- Core/API: Python + FastAPI.
- Main Telegram Bot و Reseller Bots: Python + aiogram 3.
- Admin Panel و Store Website: Next.js + React + TypeScript.
- Telegram WebApp در صورت نیاز.
- Reseller API نسخه‌بندی‌شده.
- فقط Core مستقیماً به PostgreSQL دسترسی دارد.

## 3. معماری و فناوری
Modular Monolith در V1؛ PostgreSQL، SQLAlchemy 2، Alembic، Redis، ARQ برای کارهای پس‌زمینه، REST/OpenAPI، Docker/Compose، Ubuntu Server LTS و CI/CD. ابزار Reverse Proxy و جزئیات نهایی Observability در ADR استقرار تثبیت می‌شوند. معماری باید اجرای چند Instance و جداسازی سرویس‌ها را در آینده ممکن کند، اما Microservices و Zero-Downtime در V1 الزامی نیست.

## 4. اصل مرجع
Channelها فقط رابط و مصرف‌کننده API هستند. Business Logic، هویت، قیمت، Wallet، Order، پرداخت و Provisioning فقط در Core اجرا می‌شود. هیچ Channel نباید منطق مستقل متناقض داشته باشد. Domain Events و Outbox داخلی پیش‌بینی می‌شوند؛ Broker جداگانه در V1 اجباری نیست.

## 5. هویت و StoreContext
یک User مرکزی می‌تواند در Main Store و چند Reseller Store حضور داشته باشد. Store یک موجودیت دامنه‌ای رسمی است؛ Main Store و هر Reseller Store Context مستقل دارند. عضویت، Wallet، سفارش، قیمت، گزارش و مجوزها در StoreContext تفکیک می‌شوند، ولی هویت فرد مرکزی است.
- Telegram برای کاربران Telegram.
- Website با Google و/یا Email؛ شماره موبایل الزامی نیست.
- Guest Checkout مجاز است، با دریافت شناسه قابل اتکا قبل از نهایی‌سازی.
- Account Linking باید Website و Telegram را به همان User متصل کند، بدون ساخت User تکراری.
- اگر ایمیل تأییدشده دو هویت/حساب را تطبیق دهد، اتصال خودکار به User مرکزی انجام می‌شود؛ موارد تکراری، مبهم یا متعارض باید گزارش و برای بازبینی دستی صف‌بندی شوند. از اتصال خودکار در صورت وجود تعارض هویتی جلوگیری شود.
- روش دقیق Email Auth و سیاست یکتایی سراسری ایمیل همچنان نیازمند تصمیم فنی/محصولی است.

## 6. نقش‌ها و دسترسی‌ها
نقش‌های اجرایی V1: Super Admin، Reseller، Customer. طراحی Permission-based برای آینده. Admin مرکزی همه Storeها را می‌بیند؛ Reseller فقط Store و مشتریان خودش؛ Customer فقط داده‌های شخصی خود. Authorization و StoreContext در Core بررسی می‌شود، نه با اعتماد به شناسه UI.

## 7. نمایندگان و فروشگاه‌ها
- متقاضی نمایندگی باید پیش از درخواست/فعال‌سازی، عضو و مشتری ثبت‌شده فروشگاه اصلی (Main Store) باشد؛ پس از احراز این شرط می‌تواند درخواست نمایندگی دهد و فعال‌سازی نیازمند تأیید Admin است.
- زیرنماینده در V1 نیست؛ معماری برای آینده آماده باشد.
- هر نماینده Store و Bot Token مستقل دارد.
- Branding و پیام‌های Bot قابل شخصی‌سازی است؛ تغییر قوانین مالی، محصول مرکزی، Server/Panel یا Core ممنوع.
- Admin تعیین می‌کند چه محصولی در کدام Store قابل فروش باشد.
- انتقال پول بین Resellerها ممنوع.
- Admin می‌تواند Wallet نماینده را دستی اصلاح کند؛ دلیل اختیاری، Audit اجباری.
- Reseller می‌تواند Wallet مشتریان خودش را در Store خودش شارژ کند. پول شارژ مشتری فروشگاه Reseller A به درگاه/حساب پرداخت متعلق به همان فروشنده A پرداخت می‌شود، نه درگاه یا کیف پول فروشگاه دیگری؛ پشتوانه و روش تأیید پرداخت طبق Payment Adapter و تنظیمات همان Store است.
- هر خرید نهایی فقط از Wallet مربوط به همان Store انجام می‌شود؛ خرید مستقیم با درگاه، در صورت وجود، ابتدا Wallet همان Store را شارژ می‌کند و سپس خرید از Wallet کسر می‌شود.

## 8. محصولات و قیمت
سه قیمت مستقل:
- Main Price: قیمت فروش در Main Store.
- Reseller Price: هزینه محصول که از اعتبار Reseller در Main Store کسر می‌شود؛ در V1 برای همه Resellerها یکسان.
- Customer Price: قیمت فروش Reseller به مشتریان خودش؛ قابل تعیین توسط Reseller برای هر محصول مجاز.
محصول‌ها بر اساس مدت، حجم و مشخصات سرویس تعریف می‌شوند. Product Availability به تفکیک Store کنترل می‌شود. Coupon در V1 پیاده‌سازی می‌شود: سازنده می‌تواند Admin یا Reseller مجاز باشد؛ Coupon به یک Store مشخص یا دامنه‌ای که Admin صریحاً مجاز کرده محدود است؛ Reseller فقط Couponهای Store خودش را می‌سازد و مدیریت می‌کند. Couponها در V1 به‌صورت پیش‌فرض قابل ترکیب نیستند و Core یک Coupon معتبر را طبق قاعده انتخاب مرکزی اعمال می‌کند. سقف تخفیف به مبلغ واجد شرایط و سقف تنظیم‌شده محدود است؛ شروع/پایان اعتبار و سقف مصرف کلی/هر مشتری قابل تنظیم‌اند. اعتبارسنجی Coupon فقط در Core انجام می‌شود. سفارش باید Snapshot قیمت، Coupon، تخفیف، مبلغ نهایی و Currency را حفظ کند؛ تغییر بعدی تنظیمات نباید سفارش قبلی را تغییر دهد.

## 9. VPN Account و پنل‌ها
پنل‌های V1: Sanaei و PasarGuard. هر پنل Adapter مستقل با Interface استاندارد دارد. انتخاب سرور در V1 بر اساس کمترین اکانت فعال، پس از بررسی health، ظرفیت و سازگاری Product است. Health Check، Retry، Suspend/Resume، Reconciliation و Manual Review لازم‌اند. Advanced Load Balancing برای آینده.
VPN Account موجودیت مستقل است و به User، Store، Order، Product، Server و Panel مرتبط می‌شود. Lifecycle پیشنهادی: Pending, Provisioning, Active, Suspended, Expired, Revoked, Archived. انتقال توسط مشتری و Admin در V1 غیرمجاز است. Soft Delete/Archive برای داده عملیاتی؛ سوابق مالی و Audit حذف نمی‌شوند. تمدید با افزایش هم‌زمان زمان و حجم انجام می‌شود.

## 10. سفارش و Provisioning
چرخه اصلی: Pending → Payment Pending → Paid → Processing → Provisioning → Completed.
حالات جانبی: Payment Failed، Provisioning Failed، Cancelled، Refund Pending، Refunded؛ در آینده Partially Refunded و On Hold/Manual Review.
اگر پرداخت موفق شود اما ساخت اکانت شکست بخورد، پس از Retryهای مجاز سفارش به Provisioning Failed / Manual Review می‌رود. Refund خودکار ممنوع است تا وضعیت واقعی Panel بررسی شود. Admin می‌تواند Retry، اتصال Account موجود یا Refund/اعتباردهی را انتخاب کند.
Payment، Order و Provisioning Stateهای مستقل دارند.

## 11. Wallet و Ledger
Wallet هر User در هر Store مستقل است. Ledger منبع حقیقت مالی؛ Balance صرفاً موجودی جاری/Projection است. تمام تغییرات Wallet باید Ledger داشته باشند. رکوردهای مالی Append-only و Idempotent هستند. مشتری عادی موجودی منفی ندارد؛ Reseller در Main Store می‌تواند تا Debt Limit منفی شود. گزارش مالی از Ledger استخراج می‌شود. واحد پول برای هر Store قابل تنظیم است و Currency باید روی Wallet، Ledger، Payment، Coupon و Order صریح ذخیره شود؛ تبدیل بین ارزها نباید ضمنی یا بدون نرخ/ثبت مستقل انجام شود.

## 12. خرید Reseller و Debt Limit
در خرید مشتری Reseller:
1. درخواست فقط در StoreContext همان فروشگاه و برای عضو آن Store پذیرفته می‌شود.
2. Core، محصول مجاز، Customer Price، Coupon و موجودی Wallet مشتری را بررسی می‌کند.
3. پیش از هر Debit، Debt Limit نماینده در Main Store بررسی می‌شود.
4. در یک تراکنش DB اتمیک، Debit مشتری در Wallet فروشگاه Reseller، ثبت هزینه/بدهی نماینده در Wallet او در Main Store، Order و Ledger entries هماهنگ می‌شوند.
5. پس از Commit، Outbox/ARQ Job برای Provisioning اجرا می‌شود.
اگر نماینده به Debt Limit رسیده باشد، خرید پیش از هر Debit متوقف می‌شود. فقط خرید مشتریان همان نماینده متوقف می‌شود؛ سایر Storeها فعال می‌مانند. هشدار برای نماینده و پیام راهنمای پشتیبانی برای مشتری ارسال می‌شود. سیاست عددی پیشنهادی: `debt_limit` به‌صورت مقدار مثبت ذخیره و خرید وقتی موجودی `balance <= -debt_limit` باشد متوقف شود.

## 13. پرداخت
معماری Multi-Gateway و Multi-Currency-ready. همه خریدها از Wallet همان Store کسر می‌شوند؛ درگاه/انتقال بانکی فقط برای شارژ Wallet است. هر Reseller Store می‌تواند روش پرداخت و مقصد دریافت وجه متعلق به خودش را داشته باشد؛ شارژ مشتری آن Store نباید به Main Store یا Store دیگر هدایت شود. درگاه آنلاین و سازوکار دقیق تأیید انتقال دستی هنوز باید انتخاب شوند. Payment Adapter مستقل برای هر Gateway و Store-scoped configuration لازم است. Callback تکراری نباید تراکنش یا شارژ تکراری ایجاد کند. پرداخت ارزی، Crypto و Telegram Payments در V1 اجباری نیستند.

## 14. Referral و Commission
Referral تک‌سطحی است. مدل پاداش/کمیسیون توسط Admin برای هر طرح قابل انتخاب و تنظیم است؛ برای طرح‌های درصدی، مبنا مبلغ خالص پرداخت‌شده پس از تخفیف است. Attribution بر اساس اولین معرف ثبت‌شده انجام می‌شود و تغییر معرف بعدی رابطه اولیه را جایگزین نمی‌کند. Refund باید Commission Reversal ثبت کند؛ در صورت خرج‌شدن کمیسیون، reversal در Ledger باقی می‌ماند و بازیافت از کمیسیون‌های آتی پیشنهاد پیش‌فرض است، جزئیات بدهی/منفی‌شدن کیف پول معرف نیازمند تثبیت است.

## 15. Test Account
Admin تعداد دفعات، cooldown/محدودیت زمانی و Server/Panel مجاز را تعیین می‌کند. محدودیت بر اساس Telegram ID، Email و Google Identity قابل اعمال است. درخواست‌های هم‌زمان نباید محدودیت را دور بزنند. Panel اختصاصی تست در آینده ممکن باشد.

## 16. Website و Bots
Website علاوه بر فروش، معرفی سرویس، آموزش، FAQ، قوانین و محتوای پایه دارد؛ CMS/Blog در آینده. Guest پس از خرید بتواند حساب را تکمیل و به Telegram متصل کند.
Main Bot برای مشتریان است؛ عملیات مدیریتی از Admin Panel. هر Reseller Bot Token رمزنگاری‌شده، Branding و محصولات مجاز خودش را دارد. قابلیت‌های اصلی مشتری در Bot و Website موجود باشند؛ تمام Business Logic در Core است. Telegram WebApp مجاز است.

## 17. Ticket و Notification
Ticketing پایه با فایل/تصویر در V1؛ فعلاً Admin پاسخ‌گو، با امکان چند اپراتور/Department در آینده.
Notification مرکزی برای Telegram و Web Notification؛ رویدادهای پرداخت، سفارش، VPN Account، Wallet، Referral/Commission، Ticket، خطا و Debt. Email/SMS/Push آینده‌پذیر. هر Admin و Reseller Group مستقل Telegram با Topics دارد؛ نماینده فقط رویدادهای خودش را می‌گیرد. Notification failure نباید تراکنش اصلی را تکرار کند.

## 18. امنیت و Audit
2FA برای Admin پیاده‌سازی اما اختیاری؛ IP Restriction اختیاری. Secret/Token با Encryption-at-Rest اجباری. Audit Log Append-Only/Immutable در سطح اپلیکیشن؛ تغییرات مالی، هویت، قیمت، تنظیمات، API key، Refund، Provisioning و Emergency Control ثبت شوند. Rate Limit، Anti-Brute-Force و تشخیص رویدادهای امنیتی الزامی. Backup رمزنگاری‌شده. حداقل‌سازی داده شخصی و ثبت نسخه Terms/Privacy پذیرفته‌شده.

## 19. گزارش و جست‌وجو
Admin همه گزارش‌ها؛ Reseller گزارش Store خودش؛ User فقط اطلاعات خودش. Dashboard عملیاتی نزدیک به لحظه‌ای؛ گزارش‌های سنگین Cache/Periodic Refresh. Export CSV/Excel و Search/Filter برای User، Order، VPN Account، Payment، Wallet Transaction، Ticket، Product و Reseller.

## 20. زیرساخت و پایداری
سه محیط Development، Staging، Production. Production می‌تواند ابتدا روی VPS باشد. CI/CD الزامی؛ Zero-Downtime در V1 نه، ولی توسعه آینده ممکن. Backup یک تا دو بار روزانه قابل تنظیم، Retention پیش‌فرض 30 روز، نسخه محلی و خارج سرور، رمزنگاری و Restore Test. Monitoring CPU/RAM/Queue/API Latency/Error Rate/Server/Panel health و Alert با deduplication/recovery. Runbook برای خرابی DB، VPS، Redis، Panel، Gateway، Deploy و Data Corruption.

## 21. تنظیمات و کنترل اضطراری
قیمت‌ها، Debt Limit، Test Limit، Retry، Notification Rules، Backup Retention، API enable/disable و Feature Flags Hard-code نشوند. Admin بتواند خرید، پرداخت، Reseller، Product، Panel، API، Bot و Provisioning را موقتاً متوقف کند. Maintenance Mode در سطح کل سامانه، Channel، Store یا Feature. تمام کنترل‌ها Audit شوند.

## 22. تست و Definition of Done
Unit، Integration، Contract، E2E، Security، Concurrency و Resilience Testing. جریان‌های حیاتی: Login/Linking، Guest Checkout، Payment callback تکراری، Wallet، Main/Reseller Purchase، Debt Limit، Provisioning success/failure/retry، Refund/Commission reversal، Test Account، Ticket، Notification و Reconciliation.
وضعیت قابلیت: SPECIFIED → IMPLEMENTED → TESTED → PRODUCTION VERIFIED.

## 23. API و Webhook
Reseller API نسخه‌بندی‌شده در V1 پیاده‌سازی و فعال است؛ هر Credential دارای lifecycle (Create/Activate/Disable/Rotate/Revoke)، scopes، rate limit، audit و Store isolation است و Admin می‌تواند آن را غیرفعال کند. Outgoing Webhook نیز در V1 شامل طراحی و پیاده‌سازی تحویل امن، HMAC امضا، timestamp/replay protection، retry با backoff، delivery log، idempotency و مدیریت endpoint است. Secret فقط هنگام ایجاد نمایش داده شود و به‌صورت hash/رمزنگاری‌شده مطابق کاربرد نگهداری شود.

## 24. تصمیم‌های قطعی جدید مالک محصول
- Currency برای هر Store قابل تنظیم است.
- متقاضی نمایندگی باید از قبل مشتری/عضو Main Store باشد.
- Reseller مشتریان خود را در Wallet همان Reseller Store شارژ می‌کند؛ مقصد پرداخت متعلق به همان فروشگاه است.
- همه خریدها فقط با Wallet همان Store انجام می‌شوند؛ پرداخت خارجی ابتدا Wallet را شارژ می‌کند.
- شارژ Wallet مشتری توسط Reseller مجاز است.
- Coupon در V1 با scope، سقف تخفیف، بازه اعتبار و محدودیت مصرف پیاده‌سازی می‌شود؛ سازنده Admin یا Reseller مجاز و اعتبارسنجی فقط در Core است.
- کمیسیون بر اساس طرح قابل تنظیم Admin؛ انتساب معرف بر اساس اولین معرف ثبت‌شده.
- اتصال هویت در تطبیق ایمیل تأییدشده خودکار است، اما تعارض/تکرار برای بازبینی گزارش می‌شود.
- تغییر مالک VPN Account توسط Admin مجاز نیست.
- صف کارها ARQ + Redis.
- هدف بازیابی: RPO حداکثر 24 ساعت و RTO حداکثر 8 ساعت.
- Reseller API و Outgoing Webhook در V1 پیاده‌سازی و فعال هستند.

## 25. موارد غیرالزامی در V1
Microservices، زیرنماینده، Multi-level Affiliate، Crypto، پرداخت ارزی، Admin Bot، Advanced Load Balancing و Zero-Downtime اجرایی نیستند؛ فقط قابلیت توسعه باید حفظ شود.
