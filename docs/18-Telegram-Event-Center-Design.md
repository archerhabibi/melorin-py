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
Admin: `GET/PUT/DELETE /admin/event-center`، `POST /admin/event-center/test`
Reseller: `GET/PUT/DELETE /stores/{store_id}/reseller/event-center`، `POST …/test`

## رویدادها
| Topic | منبع |
|---|---|
| payments | رسید در انتظار بررسی، پرداخت موفق/ناموفق |
| orders | سفارش پرداخت‌شده/تکمیل‌شده/بازگشت‌خورده |
| debt | `reseller.debt` (نزدیک سقف / رسیدن به سقف) |
| tickets | تیکت جدید و پاسخ مشتری |
| errors | خطای ساخت اکانت، پنل unhealthy، رویداد Outbox با شکست مکرر |
