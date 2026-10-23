# 18 — Telegram Event Center (SRS §17)

## هدف
هر Admin و هر Reseller یک **گروه تلگرام (Supergroup با Topics)** تنظیم می‌کند و رویدادهای مربوط به خودش (پرداخت، سفارش، بدهی، تیکت، خطا) در **Topic** مربوطه می‌آید. نماینده فقط رویدادهای فروشگاه خودش را می‌بیند. خطای ارسال هرگز تراکنش اصلی را تکرار یا خراب نمی‌کند.

## تصمیم‌های طراحی
1. **مدل موجود** `telegram_event_destinations` (`store_id NULL` = ادمین، وگرنه فروشگاه نماینده). فقط سه ستون وضعیت اضافه می‌شود (`last_sent_at`, `last_error`, `last_error_at`) تا پنل بتواند سلامت اتصال را نشان دهد (migration 0031).
2. **Topics**: `payments`، `orders`، `debt`، `tickets`، `errors`. هر کدام به `message_thread_id` نگاشت می‌شود؛ اگر Topic تنظیم نشده باشد پیام به General گروه می‌رود. اگر Topic در تلگرام حذف شده باشد، یک‌بار بدون thread ارسال می‌شود.
3. **Fan-out در Outbox**: `publish()` برای هر مقصد یک رویداد `eventcenter.deliver` می‌نویسد (کلید dedup = رویداد منبع + مقصد). بنابراین retry فقط همان مقصدِ ناموفق را دوباره می‌فرستد و ارسال تکراری نداریم.
4. **Tap مرکزی** در `process_event`: بعد از اجرای handler هر رویداد Outbox، قوانین `rules.py` اجرا می‌شود (داخل SAVEPOINT و best-effort). handlerهای مالی/سفارش دست نمی‌خورند.
5. **Isolation**: رویداد فروشگاه نماینده فقط به مقصد همان فروشگاه می‌رود. نسخه‌ی ادمین فقط برای `debt` و `errors` (با پیشوند نام فروشگاه). رویداد Main Store به مقصد ادمین می‌رود.
6. **امنیت**: ربات نماینده فقط با **توکن ربات خود نماینده** پیام می‌فرستد (جلوگیری از سوءاستفاده از ربات اصلی برای اسپم). ادمین با ربات اصلی. `chat_id` فقط عددی (`-100…`) و اعتبارسنجی‌شده است. تغییرات در Audit ثبت می‌شود.
7. **خطای دائمی** (400/403/404 تلگرام: ربات حذف شده، گروه نامعتبر) ثبت در `last_error` و بدون retry؛ خطای موقت (429/5xx/شبکه) با backoff Outbox دوباره تلاش می‌شود.

## API
Admin: `GET/PUT/DELETE /admin/event-center`، `POST /admin/event-center/test`، `POST …/check`، `POST …/provision`
Reseller: `GET/PUT/DELETE /stores/{store_id}/reseller/event-center`، `POST …/test`، `POST …/check`، `POST …/provision`

## رویدادها
| Topic | منبع |
|---|---|
| payments | رسید در انتظار بررسی، پرداخت موفق/ناموفق |
| orders | سفارش پرداخت‌شده/تکمیل‌شده/بازگشت‌خورده |
| debt | `reseller.debt` (نزدیک سقف / رسیدن به سقف) |
| tickets | تیکت جدید و پاسخ مشتری |
| errors | خطای ساخت اکانت، پنل unhealthy، رویداد Outbox با شکست مکرر |

## وضعیت پیاده‌سازی
- Backend: `modules/eventcenter/{service,rules,routes,schemas,topics}.py`، migration `0031`، handler `eventcenter.deliver` در worker، tap مرکزی پس از هر handler.
- UI: صفحهٔ «مرکز رویداد» در پنل ادمین و تب «مرکز رویداد» در پنل نماینده (ذخیره، تست واقعی هر Topic، وضعیت سلامت، حذف).
- تست: `apps/api/tests/test_event_center.py` (۱۴ تست) و `apps/admin-web/tests/event-center.test.jsx`.
- «پنل unhealthy» اکنون قانون جدا دارد: `rules.notify_panel_health` در job سلامت پنل (هر ۵ دقیقه) و بررسی دستی ادمین فراخوانی می‌شود و **فقط هنگام تغییر وضعیت** (سالم به ناسالم، و بازگشت به سالم) به Topic «خطاها»ی گروه ادمین پیام می‌دهد؛ پنلی که ناسالم می‌ماند پیام تکراری نمی‌فرستد.
- تیکت: فقط پیام خود مشتری اعلام می‌شود (رویداد `ticket.updated` شناسهٔ `message_id` را دارد)؛ تغییر وضعیت/اولویت، پاسخ پشتیبان و یادداشت داخلی ساکت‌اند.
- باقی‌مانده: خطای ساخت اکانت (`provisioning.failed`) و شکست مکرر Outbox از قبل در Topic «خطاها» می‌آید؛ مورد دیگری باز نیست.

## بررسی گروه و ساخت خودکار Topic (الهام از `syncReportTopics` در mirzabot)
- **`check`** (فقط‌خواندنی): با `getMe` + `getChat` + `getChatMember` بررسی می‌کند گروه سوپرگروه باشد، ربات عضو/مجاز به ارسال باشد، Topics روشن باشد و ربات برای ساخت Topic دسترسی Manage Topics داشته باشد. خروجی: `problems` به فارسی + `missing_topics`.
- **`provision`**: برای هر Topic که شناسه ندارد `createForumTopic` (با نام فارسی همان Topic) می‌زند و `message_thread_id` را ذخیره می‌کند. شناسهٔ موجودِ سالم هرگز تغییر نمی‌کند (و نام Topic هم دست نمی‌خورد)؛ اجرای دوباره Topic تکراری نمی‌سازد. هر شناسهٔ ذخیره‌شده اول با `reopenForumTopic` (مثل `syncReportTopics` در mirzabot ولی بدون تغییر نام) راستی‌آزمایی می‌شود: `TOPIC_NOT_MODIFIED` یعنی Topic هست؛ «message thread not found» یعنی در گروه حذف شده و دوباره ساخته می‌شود (`status: recreated`، Audit `event_center.topic_recreated` با `old_thread_id`). خطای نامرتبط (۴۲۹، دسترسی، شبکه) هرگز باعث ساخت دوباره نمی‌شود؛ همان‌جا `failed` گزارش می‌شود. بعد از ساخت هر Topic commit می‌شود، پس خطای وسط کار (دسترسی/۴۲۹) شناسه‌های ساخته‌شده را از دست نمی‌دهد و ردیف مقصد قفل (`FOR UPDATE`) است تا دوبار کلیک Topic دوبل نسازد. هر Topic ساخته‌شده در Audit (`event_center.topic_created`) ثبت می‌شود.
- خطاهای تلگرام به پیام عملی تبدیل می‌شوند (`EVENT_CENTER_NOT_FORUM`، `…_NO_RIGHTS`، `…_CHAT_NOT_FOUND`، `…_BOT_REMOVED`، `…_BAD_TOKEN`، `…_TELEGRAM_UNAVAILABLE`).
- ایزولیشن مثل ارسال: ادمین با ربات اصلی، نماینده فقط با ربات خودش.
