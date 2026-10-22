# مشخصات کانال‌ها
## Admin Panel
مدیریت Users/Identities/Stores/Resellers، درخواست نمایندگی، Product/Categories/availability/pricing، Server/Panel/health، Orders/Payments/Refunds/Wallet/Ledger، Debt Limit، VPN Accounts، Retry/Manual Review، Referral/Commission، Test policies، Ticket/attachments، Notifications/Telegram Topics، API credentials، Feature Flags، Maintenance/Emergency، Audit، security events، backup status، health و reports/export. فقط API مرکزی؛ 2FA/IP restriction قابل تنظیم؛ عملیات حساس Audit شوند.
## Store Website
صفحات معرفی، سرویس، آموزش، FAQ، قوانین؛ catalog/checkout/order status؛ Guest Checkout؛ Google/Email login؛ داشبورد سفارش‌ها، VPN accounts، Wallet، تراکنش‌ها و Referral شخصی؛ Telegram linking؛ Ticket و Web Notification. هر خرید فقط با Wallet همان Store نهایی می‌شود؛ درگاه فقط برای شارژ Wallet استفاده می‌شود. هر Store ارز و مقصد پرداخت/تنظیمات شارژ خودش را دارد. Coupon در رابط نمایش داده می‌شود اما اعتبارسنجی و انتخاب نهایی فقط در Core است. CMS/Blog آینده. منطق کسب‌وکار فقط در Core.
## Main Telegram Bot
خرید، استعلام/تمدید، Wallet/شارژ، حساب کاربری و سفارش‌ها، قوانین/آموزش، Referral، Ticket، Test Account، مدیریت اکانت‌های خود کاربر و اعلان‌ها. عملیات Admin ندارد.
## Reseller Bot
فروش محصولات مجاز، مدیریت مشتریان عضو Store خودش، Customer Price، گزارش فروش، Wallet/debt status، شارژ Wallet مشتریان خودش در Store خودش، Couponهای همان Store، Branding/messages، هشدار Debt و اعلان‌های Store خودش. مشتری باید برای خرید در همان Store عضویت داشته باشد؛ تمام سفارش‌ها از Wallet همان Store پرداخت می‌شوند و شارژ به مقصد پرداخت همان فروشنده هدایت می‌شود. Token رمزنگاری‌شده؛ دسترسی مستقیم به Server/Panel و داده دیگر Resellerها ممنوع.
## Reseller API
`/api/v1`، credential lifecycle، scopes، rate limit، audit، Store isolation و قابلیت disable توسط Admin. دسترسی عمومی گسترده تا تکمیل Threat Model غیرفعال بماند.
## Telegram Group Event Center
Group مستقل Admin و هر Reseller؛ Topics مانند Payments، Orders، Provisioning، Errors، Customers، Wallet، Security و System. Routing بر اساس StoreContext، retry/deduplication، عدم ارسال Secret یا داده غیرضروری. اختیارات تغییر Group/Topic در RBAC نهایی شود.

## Coupon Management
Admin می‌تواند Couponهای هر Store یا دامنه‌ای را که صریحاً مجاز کرده ایجاد و مدیریت کند. Reseller فقط Couponهای Store خودش را ایجاد/مدیریت می‌کند. UI می‌تواند quote/validation را درخواست کند، اما اعتبار نهایی، سقف مصرف، scope، سقف تخفیف و انتخاب Coupon فقط در Core است.

## Telegram scope and evidence

The Telegram channel is a transport boundary. Core owns identity, StoreContext, catalog, wallet, order, VPN, reseller and ticket rules. The current executable evidence covers authentication/update validation, Core API transport, notification delivery with dedup/retry, and the documented channel boundaries.

The following are deliberately not described as complete without runtime bot deployment evidence: every aiogram command handler, every callback mutation, Telegram Event Center topic provisioning, and full reseller mutation coverage. Production acceptance requires Telegram sandbox tests for duplicate update replay, restart/replay, payment/order idempotency, ticket mutation, and topic delivery.

### Update (bot handlers)

Both runners now implement the command/callback set listed in their READMEs (plain Telegram Bot API over httpx, no aiogram). Covered by offline tests in `apps/api/tests/test_telegram_bot_flows.py` (mocked Telegram + Core): idempotent purchase callback, top-up + receipt state, Core error reporting, reseller Store binding.

Still open (needs sandbox evidence): live Telegram duplicate-update/restart replay, Event Center topic provisioning, reseller write operations beyond payment review, and the test-account order is recorded with channel `web` by Core.

### Update (reseller request from the bot)

`/reseller` in the main bot is a two-step flow: request first, then (after admin approval, status `awaiting_details`) domain + bot token collected in the chat. The token message is deleted after it is read and the token never enters the bot's state file or logs; Core validates and stores it encrypted. Covered offline by `apps/api/tests/test_reseller_telegram_flow.py` and `test_o01_reseller_applications.py`. Still needs sandbox evidence: that Telegram really lets the bot delete the user's message in every chat type (best effort; the flow continues if it cannot).

## طراحی ربات نماینده (Reseller Bot)

### اصل طراحی
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

### جریان کامل
1. مشتری در ربات main دستور `/reseller` را می‌زند → درخواست ثبت می‌شود.
2. ادمین تأیید می‌کند → متقاضی دامنه و توکن را در تلگرام می‌فرستد → فروشگاه + binding ساخته می‌شود.
3. **حداکثر ۳۰ ثانیه بعد** Supervisor ربات را بالا می‌آورد و وضعیت «متصل» در پنل ادمین دیده می‌شود (بدون ری‌استارت).

### قواعد چرخهٔ عمر
| رویداد در ادمین | رفتار ربات |
|---|---|
| ثبت/تغییر توکن | ربات قبلی متوقف و با توکن جدید شروع می‌شود |
| خاموش‌کردن ربات یا تعلیق فروشگاه | ربات متوقف می‌شود (وضعیت: غیرفعال / تعلیق) |
| قطع ارتباط ربات | توکن پاک و binding حذف؛ ربات آزاد می‌شود |
| توکن در BotFather باطل شد | تلگرام 401 می‌دهد → وضعیت «خطا»، تلاش بی‌پایان نمی‌شود تا توکن جدید ثبت شود |
| ربات جای دیگری هم getUpdates می‌گیرد | وضعیت «خطا: هم‌زمان…» (با deleteWebhook هنگام شروع) |
| Supervisor متوقف شد | بعد از ~۲ دقیقه وضعیت «قطع» نمایش داده می‌شود |
| Core در دسترس نیست | رباتهای در حال اجرا ادامه می‌دهند |

### تجربهٔ کاربر در ربات
* **مشتری:** فروشگاه با نام و متن‌های خود نماینده (خوش‌آمد، پشتیبانی، قوانین)؛ گزینهٔ «درخواست نمایندگی» نمایش داده نمی‌شود.
* **مالک:** دکمهٔ «🏪 مدیریت فروشگاه» و منوی دستورات اختصاصی (`/manage /report /customers /payments /prices`)؛
  تشخیص مالک بودن با Core است (۴۰۳ برای دیگران). صفحهٔ مدیریت: اعتبار/بدهی، تعداد پرداخت‌های در انتظار، میان‌بُر گزارش، مشتریان، قیمت‌ها و ورود به وب.

### پنل ادمین → نمایندگان
فهرست با وضعیت زندهٔ ربات و فیلتر (متصل / دارای مشکل / غیرفعال / تعلیق). در Drawer ویرایش:
نام، دامنه (اعتبارسنجی + یکتایی)، وضعیت، سقف بدهی، فروش، API، روشن/خاموش‌بودن ربات،
توکن (فقط نوشتنی؛ با تلگرام تأیید می‌شود و هرگز برنمی‌گردد)، و متن‌های ربات. همهٔ تغییرات در ممیزی ثبت می‌شود (قبل/بعد).

### امنیت
* مسیر `/api/v1/internal/*` فقط روی شبکهٔ خصوصی: در Caddy و nginx مسدود است، با `X-Bot-Secret` محافظت می‌شود و اگر هدر `X-Forwarded-*` داشته باشد رد می‌شود.
* توکن‌ها رمزنگاری‌شده در DB؛ فقط به Supervisor داده می‌شوند؛ در لاگ‌ها (`bot<redacted>`) و در پاسخ‌های ادمین هرگز نیستند.
* گزارش وضعیتِ توکن قدیمی (fingerprint نامطابق) نادیده گرفته می‌شود.
