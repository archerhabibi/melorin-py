# ارتباطات و پشتیبانی / Communication & Support

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** Tickets، Notifications، Event Center، Broadcast و پشتیبانی.

**جایگاه در پنل:** گروه ترکیبی «اعلان‌ها، ارتباطات و پشتیبانی» شامل Broadcast، Event Center و تیکت‌ها است؛ دامنهٔ بک‌اند Tickets مستقل می‌ماند. Event Center: رویدادهای ادمین در گروه تلگرام با Topicهای خودکار و گزارش شبانه. دکمه‌های رنگی/پریمیوم تلگرام در «سیستم و امنیت» و فقط با دسترسی `system` قابل ویرایش است. مشخصات کانال‌ها (پنل، وب، ربات‌ها، Reseller API) در مواد ادغام‌شده است.

## English section

**Purpose:** Tickets, Notifications, Event Center, Broadcast and support.

**In the panel:** the combined group "Notifications, Communication & Support" holds Broadcast, Event Center and Tickets; the Tickets backend domain stays independent. Event Center posts admin events to a Telegram group with automatic Topics and a nightly report. The coloured/premium Telegram buttons live in "System & Security" and are editable only with `system` access. Channel specifications (panel, web, bots, Reseller API) are in the merged material.

## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `16-COMMUNICATION-SUPPORT.md`

#### 18 — Telegram Event Center (SRS §17)

##### هدف
هر Admin و هر Reseller یک **گروه تلگرام (Supergroup با Topics)** تنظیم می‌کند و رویدادهای مربوط به خودش (پرداخت، سفارش، بدهی، تیکت، خطا) در **Topic** مربوطه می‌آید. نماینده فقط رویدادهای فروشگاه خودش را می‌بیند. خطای ارسال هرگز تراکنش اصلی را تکرار یا خراب نمی‌کند.

##### تصمیم‌های طراحی
1. **مدل موجود** `telegram_event_destinations` (`store_id NULL` = ادمین، وگرنه فروشگاه نماینده). فقط سه ستون وضعیت اضافه می‌شود (`last_sent_at`, `last_error`, `last_error_at`) تا پنل بتواند سلامت اتصال را نشان دهد (migration 0031).
2. **Topics** (۹ تا؛ الهام از Topicهای گزارش در mirzabot): `payments`، `orders`، `debt`، `tickets`، `errors`، `daily` (گزارش شبانه)، `affiliate` (کمیسیون و معرف)، `tests` (اکانت تست)، `backup` (پشتیبان‌گیری). گروه **ادمین** هر ۹ تا را دارد؛ گروه **نماینده** فقط ۷ Topic سطح فروشگاه را (`affiliate` و `backup` مخصوص ادمین‌اند: بکاپ سطح پلتفرم است و رفرال فقط در Main Store وجود دارد، پس Topic نماینده همیشه خالی می‌ماند). ذخیرهٔ شناسهٔ Topic ادمینی برای نماینده 422 می‌دهد و UI نماینده آن را نشان نمی‌دهد. هر کدام به `message_thread_id` نگاشت می‌شود؛ اگر Topic تنظیم نشده باشد پیام به General گروه می‌رود. اگر Topic در تلگرام حذف شده باشد، یک‌بار بدون thread ارسال می‌شود.
3. **Fan-out در Outbox**: `publish()` برای هر مقصد یک رویداد `eventcenter.deliver` می‌نویسد (کلید dedup = رویداد منبع + مقصد). بنابراین retry فقط همان مقصدِ ناموفق را دوباره می‌فرستد و ارسال تکراری نداریم.
4. **Tap مرکزی** در `process_event`: بعد از اجرای handler هر رویداد Outbox، قوانین `rules.py` اجرا می‌شود (داخل SAVEPOINT و best-effort). handlerهای مالی/سفارش دست نمی‌خورند.
5. **Isolation**: رویداد فروشگاه نماینده فقط به مقصد همان فروشگاه می‌رود. نسخه‌ی ادمین فقط برای `debt` و `errors` (با پیشوند نام فروشگاه). رویداد Main Store به مقصد ادمین می‌رود.
6. **امنیت**: ربات نماینده فقط با **توکن ربات خود نماینده** پیام می‌فرستد (جلوگیری از سوءاستفاده از ربات اصلی برای اسپم). ادمین با ربات اصلی. `chat_id` فقط عددی (`-100…`) و اعتبارسنجی‌شده است. تغییرات در Audit ثبت می‌شود.
7. **خطای دائمی** (400/403/404 تلگرام: ربات حذف شده، گروه نامعتبر) ثبت در `last_error` و بدون retry؛ خطای موقت (429/5xx/شبکه) با backoff Outbox دوباره تلاش می‌شود.

##### API
Admin: `GET/PUT/DELETE /admin/event-center`، `POST /admin/event-center/test`، `POST …/check`، `POST …/provision`
Reseller: `GET/PUT/DELETE /stores/{store_id}/reseller/event-center`، `POST …/test`، `POST …/check`، `POST …/provision`

##### رویدادها
| Topic | منبع |
|---|---|
| payments | رسید در انتظار بررسی، پرداخت موفق/ناموفق |
| orders | سفارش پرداخت‌شده/تکمیل‌شده/بازگشت‌خورده |
| debt | `reseller.debt` (نزدیک سقف / رسیدن به سقف) |
| tickets | تیکت جدید و پاسخ مشتری |
| errors | خطای ساخت اکانت، پنل unhealthy، رویداد Outbox با شکست مکرر |
| tests | اکانت تست ساخته‌شد (`order.kind = test` هنگام تکمیل)؛ پرداخت/استرداد سفارش تست ساکت است و در «سفارش‌ها» نمی‌آید |
| affiliate (فقط ادمین) | معرف جدید، پاداش اولین خرید / کمیسیون واریزشده، برگشت کمیسیون هنگام استرداد (و بدهی باقی‌ماندهٔ معرف) |
| backup (فقط ادمین) | نتیجهٔ هر اجرای `backup_job`: موفق (با/بدون کپی S3)، ناقص (محلی OK ولی S3 ناموفق)، ناموفق. مسیر فایل روی سرور هرگز ارسال نمی‌شود |
| daily | گزارش شبانه (پایین) |

##### گزارش شبانه
`worker.jobs_reports.daily_report_job` با cron ساعت 20:30 UTC (= ۰۰:۰۰ تهران) اجرا می‌شود و برای هر گروهِ فعال یک خلاصهٔ ۲۴ ساعت گذشته می‌سازد (`eventcenter/report.py`): فروش (به‌تفکیک ارز، بدون اکانت تست)، پرداخت موفق/ناموفق، اکانت تست، تیکت جدید، و آنچه الان منتظر شماست (رسید در انتظار، تیکت باز، سفارش نیازمند بررسی). گروه ادمین اعداد کل پلتفرم + معرف و کمیسیون را می‌گیرد؛ گروه نماینده فقط اعداد فروشگاه خودش را (بدون خط معرف). کلید dedup = `daily:<تاریخ تهران>:<store|admin>`، پس اجرای دوبارهٔ cron یا ری‌استارت ورکر یک شب را دوبار نمی‌فرستد. اگر ورکر با ساعت غیر UTC اجرا شود cron باید متناسب تنظیم شود.

##### وضعیت پیاده‌سازی
- Backend: `modules/eventcenter/{service,rules,routes,schemas,topics}.py`، migration `0031`، handler `eventcenter.deliver` در worker، tap مرکزی پس از هر handler.
- UI: صفحهٔ «مرکز رویداد» در پنل ادمین و تب «مرکز رویداد» در پنل نماینده (ذخیره، تست واقعی هر Topic، وضعیت سلامت، حذف).
- تست: `apps/api/tests/test_event_center.py`، `test_event_center_extra_topics.py` (Topicهای جدید) و `apps/admin-web/tests/event-center.test.jsx`.
- «پنل unhealthy» اکنون قانون جدا دارد: `rules.notify_panel_health` در job سلامت پنل (هر ۵ دقیقه) و بررسی دستی ادمین فراخوانی می‌شود و **فقط هنگام تغییر وضعیت** (سالم به ناسالم، و بازگشت به سالم) به Topic «خطاها»ی گروه ادمین پیام می‌دهد؛ پنلی که ناسالم می‌ماند پیام تکراری نمی‌فرستد.
- تیکت: فقط پیام خود مشتری اعلام می‌شود (رویداد `ticket.updated` شناسهٔ `message_id` را دارد)؛ تغییر وضعیت/اولویت، پاسخ پشتیبان و یادداشت داخلی ساکت‌اند.
- باقی‌مانده: خطای ساخت اکانت (`provisioning.failed`) و شکست مکرر Outbox از قبل در Topic «خطاها» می‌آید؛ مورد دیگری باز نیست.

##### بررسی گروه و ساخت خودکار Topic (الهام از `syncReportTopics` در mirzabot)
- **`check`** (فقط‌خواندنی): با `getMe` + `getChat` + `getChatMember` بررسی می‌کند گروه سوپرگروه باشد، ربات عضو/مجاز به ارسال باشد، Topics روشن باشد و ربات برای ساخت Topic دسترسی Manage Topics داشته باشد. خروجی: `problems` به فارسی + `missing_topics`.
- **`provision`**: برای هر Topic که شناسه ندارد `createForumTopic` (با نام فارسی همان Topic) می‌زند و `message_thread_id` را ذخیره می‌کند. شناسهٔ موجودِ سالم هرگز تغییر نمی‌کند (و نام Topic هم دست نمی‌خورد)؛ اجرای دوباره Topic تکراری نمی‌سازد. هر شناسهٔ ذخیره‌شده اول با `reopenForumTopic` (مثل `syncReportTopics` در mirzabot ولی بدون تغییر نام) راستی‌آزمایی می‌شود: `TOPIC_NOT_MODIFIED` یعنی Topic هست؛ «message thread not found» یعنی در گروه حذف شده و دوباره ساخته می‌شود (`status: recreated`، Audit `event_center.topic_recreated` با `old_thread_id`). خطای نامرتبط (۴۲۹، دسترسی، شبکه) هرگز باعث ساخت دوباره نمی‌شود؛ همان‌جا `failed` گزارش می‌شود. بعد از ساخت هر Topic commit می‌شود، پس خطای وسط کار (دسترسی/۴۲۹) شناسه‌های ساخته‌شده را از دست نمی‌دهد و ردیف مقصد قفل (`FOR UPDATE`) است تا دوبار کلیک Topic دوبل نسازد. هر Topic ساخته‌شده در Audit (`event_center.topic_created`) ثبت می‌شود.
- خطاهای تلگرام به پیام عملی تبدیل می‌شوند (`EVENT_CENTER_NOT_FORUM`، `…_NO_RIGHTS`، `…_CHAT_NOT_FOUND`، `…_BOT_REMOVED`، `…_BAD_TOKEN`، `…_TELEGRAM_UNAVAILABLE`).
- ایزولیشن مثل ارسال: ادمین با ربات اصلی، نماینده فقط با ربات خودش.

### منبع / Source: `16-COMMUNICATION-SUPPORT.md`

#### مشخصات کانال‌ها
##### Admin Panel
مدیریت Users/Identities/Stores/Resellers، درخواست نمایندگی، Product/Categories/availability/pricing، Server/Panel/health، Orders/Payments/Refunds/Wallet/Ledger، Debt Limit، VPN Accounts، Retry/Manual Review، Referral/Commission، Test policies، Ticket/attachments، Notifications/Telegram Topics، API credentials، Feature Flags، Maintenance/Emergency، Audit، security events، backup status، health و reports/export. فقط API مرکزی؛ 2FA/IP restriction قابل تنظیم؛ عملیات حساس Audit شوند.
##### Store Website
صفحات معرفی، سرویس، آموزش، FAQ، قوانین؛ catalog/checkout/order status؛ Guest Checkout؛ Google/Email login؛ داشبورد سفارش‌ها، VPN accounts، Wallet، تراکنش‌ها و Referral شخصی؛ Telegram linking؛ Ticket و Web Notification. هر خرید فقط با Wallet همان Store نهایی می‌شود؛ درگاه فقط برای شارژ Wallet استفاده می‌شود. هر Store ارز و مقصد پرداخت/تنظیمات شارژ خودش را دارد. Coupon در رابط نمایش داده می‌شود اما اعتبارسنجی و انتخاب نهایی فقط در Core است. CMS/Blog آینده. منطق کسب‌وکار فقط در Core.
##### Main Telegram Bot
خرید، استعلام/تمدید، Wallet/شارژ، حساب کاربری و سفارش‌ها، قوانین/آموزش، Referral، Ticket، Test Account، مدیریت اکانت‌های خود کاربر و اعلان‌ها. عملیات Admin ندارد.
##### Reseller Bot
فروش محصولات مجاز، مدیریت مشتریان عضو Store خودش، Customer Price، گزارش فروش، Wallet/debt status، شارژ Wallet مشتریان خودش در Store خودش، Couponهای همان Store، Branding/messages، هشدار Debt و اعلان‌های Store خودش. مشتری باید برای خرید در همان Store عضویت داشته باشد؛ تمام سفارش‌ها از Wallet همان Store پرداخت می‌شوند و شارژ به مقصد پرداخت همان فروشنده هدایت می‌شود. Token رمزنگاری‌شده؛ دسترسی مستقیم به Server/Panel و داده دیگر Resellerها ممنوع.
##### Reseller API
`/api/v1`، credential lifecycle، scopes، rate limit، audit، Store isolation و قابلیت disable توسط Admin. دسترسی عمومی گسترده تا تکمیل Threat Model غیرفعال بماند.
##### Telegram Group Event Center
Group مستقل Admin و هر Reseller؛ Topics مانند Payments، Orders، Provisioning، Errors، Customers، Wallet، Security و System. Routing بر اساس StoreContext، retry/deduplication، عدم ارسال Secret یا داده غیرضروری. اختیارات تغییر Group/Topic در RBAC نهایی شود.

##### Coupon Management
Admin می‌تواند Couponهای هر Store یا دامنه‌ای را که صریحاً مجاز کرده ایجاد و مدیریت کند. Reseller فقط Couponهای Store خودش را ایجاد/مدیریت می‌کند. UI می‌تواند quote/validation را درخواست کند، اما اعتبار نهایی، سقف مصرف، scope، سقف تخفیف و انتخاب Coupon فقط در Core است.

##### Telegram scope and evidence

The Telegram channel is a transport boundary. Core owns identity, StoreContext, catalog, wallet, order, VPN, reseller and ticket rules. The current executable evidence covers authentication/update validation, Core API transport, notification delivery with dedup/retry, and the documented channel boundaries.

The following are deliberately not described as complete without runtime bot deployment evidence: every aiogram command handler, every callback mutation, Telegram Event Center topic provisioning, and full reseller mutation coverage. Production acceptance requires Telegram sandbox tests for duplicate update replay, restart/replay, payment/order idempotency, ticket mutation, and topic delivery.

###### Update (bot handlers)

Both runners now implement the command/callback set listed in their READMEs (plain Telegram Bot API over httpx, no aiogram). Covered by offline tests in `apps/api/tests/test_telegram_bot_flows.py` (mocked Telegram + Core): idempotent purchase callback, top-up + receipt state, Core error reporting, reseller Store binding.

Still open (needs sandbox evidence): live Telegram duplicate-update/restart replay, Event Center topic provisioning, reseller write operations beyond payment review, and the test-account order is recorded with channel `web` by Core.

###### Update (reseller request from the bot)

`/reseller` in the main bot is a two-step flow: request first, then (after admin approval, status `awaiting_details`) domain + bot token collected in the chat. The token message is deleted after it is read and the token never enters the bot's state file or logs; Core validates and stores it encrypted. Covered offline by `apps/api/tests/test_reseller_telegram_flow.py` and `test_o01_reseller_applications.py`. Still needs sandbox evidence: that Telegram really lets the bot delete the user's message in every chat type (best effort; the flow continues if it cannot).

##### طراحی ربات نماینده (Reseller Bot)

###### اصل طراحی
ربات نماینده «شبیه main» است و همهٔ منطق (هویت، قیمت، کیف پول، سفارش، تأیید پرداخت) در **Core** می‌ماند؛ ربات فقط حمل‌ونقل است.
تفاوت اصلی با قبل: **Core تعیین می‌کند کدام رباتِ نماینده روشن باشد**، نه فایل `.env`.

```
Admin → «نمایندگان» ──PATCH/PUT──▶ Core (DB: stores, توکن رمزنگاری‌شده)
                                      ▲   │ GET /internal/reseller-bots   (هر ~۳۰ ثانیه)
        وضعیت زنده (متصل/خطا/قطع) ◀───┘   ▼
                                  telegram_reseller (Supervisor)
                                   ├─ Runner فروشگاه A (توکن A، offset و state جدا)
                                   ├─ Runner فروشگاه B …
                                   └─ POST /internal/reseller-bots/{id}/status
```

###### جریان کامل
1. مشتری در ربات main دستور `/reseller` را می‌زند → درخواست ثبت می‌شود.
2. ادمین تأیید می‌کند → متقاضی دامنه و توکن را در تلگرام می‌فرستد → فروشگاه + binding ساخته می‌شود.
3. **حداکثر ۳۰ ثانیه بعد** Supervisor ربات را بالا می‌آورد و وضعیت «متصل» در پنل ادمین دیده می‌شود (بدون ری‌استارت).

###### قواعد چرخهٔ عمر
| رویداد در ادمین | رفتار ربات |
|---|---|
| ثبت/تغییر توکن | ربات قبلی متوقف و با توکن جدید شروع می‌شود |
| خاموش‌کردن ربات یا تعلیق فروشگاه | ربات متوقف می‌شود (وضعیت: غیرفعال / تعلیق) |
| قطع ارتباط ربات | توکن پاک و binding حذف؛ ربات آزاد می‌شود |
| توکن در BotFather باطل شد | تلگرام 401 می‌دهد → وضعیت «خطا»، تلاش بی‌پایان نمی‌شود تا توکن جدید ثبت شود |
| ربات جای دیگری هم getUpdates می‌گیرد | وضعیت «خطا: هم‌زمان…» (با deleteWebhook هنگام شروع) |
| Supervisor متوقف شد | بعد از ~۲ دقیقه وضعیت «قطع» نمایش داده می‌شود |
| Core در دسترس نیست | رباتهای در حال اجرا ادامه می‌دهند |

###### تجربهٔ کاربر در ربات
* **مشتری:** فروشگاه با نام و متن‌های خود نماینده (خوش‌آمد، پشتیبانی، قوانین)؛ گزینهٔ «درخواست نمایندگی» نمایش داده نمی‌شود.
* **مالک:** دکمهٔ «🏪 مدیریت فروشگاه» و منوی دستورات اختصاصی (`/manage /report /customers /payments /prices`)؛
  تشخیص مالک بودن با Core است (۴۰۳ برای دیگران). صفحهٔ مدیریت: اعتبار/بدهی، تعداد پرداخت‌های در انتظار، میان‌بُر گزارش، مشتریان، قیمت‌ها و ورود به وب.

###### پنل ادمین → نمایندگان
فهرست با وضعیت زندهٔ ربات و فیلتر (متصل / دارای مشکل / غیرفعال / تعلیق). در Drawer ویرایش:
نام، دامنه (اعتبارسنجی + یکتایی)، وضعیت، سقف بدهی، فروش، API، روشن/خاموش‌بودن ربات،
توکن (فقط نوشتنی؛ با تلگرام تأیید می‌شود و هرگز برنمی‌گردد)، و متن‌های ربات. همهٔ تغییرات در ممیزی ثبت می‌شود (قبل/بعد).

###### امنیت
* مسیر `/api/v1/internal/*` فقط روی شبکهٔ خصوصی: در Caddy و nginx مسدود است، با `X-Bot-Secret` محافظت می‌شود و اگر هدر `X-Forwarded-*` داشته باشد رد می‌شود.
* توکن‌ها رمزنگاری‌شده در DB؛ فقط به Supervisor داده می‌شوند؛ در لاگ‌ها (`bot<redacted>`) و در پاسخ‌های ادمین هرگز نیستند.
* گزارش وضعیتِ توکن قدیمی (fingerprint نامطابق) نادیده گرفته می‌شود.

##### دکمه‌های رنگی و پریمیوم تلگرام (Button styles)

- **هدف:** ادمین از پنل وب («دکمه‌های تلگرام») رنگ دکمه‌ها (آبی/سبز/قرمز)، ایموجی پریمیوم و تزئین متن را برای ربات اصلی و همهٔ ربات‌های نماینده یک‌جا تعیین می‌کند. بر پایهٔ فیلدهای `style` و `icon_custom_emoji_id` در Bot API 9.4.
- **ذخیره:** تنظیمات در کلید `integration.telegram_button_styles` (جدول settings) ذخیره می‌شود؛ مسیر عمومی `PUT /admin/settings/...` اجازهٔ تغییر آن را ندارد. ویرایش فقط با `GET/PUT /admin/telegram/button-styles` (اعتبارسنجی + ممیزی `integration.telegram.button_styles.updated`) و ارسال نمونه با `POST /admin/telegram/button-styles/preview` به تلگرام خود ادمین.
- **انتشار:** ربات‌ها `GET /telegram/button-styles` را (بدون احراز هویت، بدون هیچ راز) هر ۶۰ ثانیه می‌گیرند؛ بدون ری‌استارت اعمال می‌شود. خاموش یا خطا = دکمهٔ ساده.
- **قانون‌ها:** کلید دکمه همان `callback_data` است (تطبیق دقیق یا پیشوندی؛ قانون دقیق و پیشوند بلندتر مقدم است)؛ دکمه‌های لینک با کلید `@url`؛ دکمه‌های کیبورد پایین با متن دقیق. **متن کیبورد پایین هرگز تغییر نمی‌کند** (ربات منو را از روی همان متن تشخیص می‌دهد)، فقط رنگ و ایموجی.
- **محدودیت تلگرام:** ایموجی پریمیوم فقط وقتی نمایش داده می‌شود که صاحب ربات Premium داشته باشد (یا ربات نام کاربری Fragment خریده باشد). اگر تلگرام دکمهٔ استایل‌دار را رد کند (۴۰۰)، ربات همان پیام را بدون استایل دوباره می‌فرستد و هیچ پیامی گم نمی‌شود.
- **اعتبارسنجی:** شناسهٔ ایموجی پریمیوم باید مثل شناسهٔ واقعی تلگرام باشد (۵ تا ۱۹ رقم، بدون صفر ابتدایی و حداکثر `2^63-1`)؛ فیلدهای متنی (کلید، پیشوند، پسوند، یادداشت) فقط رشتهٔ واقعی پذیرفته می‌شوند؛ کلید دکمه نباید خط جدید/نویسهٔ کنترلی یا فقط نویسهٔ نامرئی داشته باشد؛ پیشوند/پسوندِ فقط‌فاصله یا فقط‌نامرئی (مثل zero-width) «تزئین» حساب نمی‌شود. «ارسال نمونه» دقیقاً همان دکمه‌های پیش‌نمایش زندهٔ پنل را (از جمله دکمهٔ لینک) به تلگرام ادمین می‌فرستد. ربات هم قانون ناقص یا نامعتبری را که از Core بگیرد دور می‌ریزد و هرگز کیبورد را خراب نمی‌کند. خطای «ارسال نمونه» علت واقعی را نشان می‌دهد (ربات بلاک/Start‌نشده، توکن نامعتبر، محدودیت تلگرام، قطعی شبکه، یا ردشدن استایل).
- **کد:** `melorin/domain/button_style.py` (اعتبارسنجی، کاتالوگ، الگوها، تطبیق)، `modules/admin/button_styles.py`، `apps/telegram-main/tgmain/ui.py` + `client.py`، `apps/admin-web/src/features/settings/ButtonStylesView.tsx`.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
