# تکمیل F021 تا F023 ملورین

F021 تأیید و حفظ شد: خروجی CSV سفارش‌ها از Admin Web با `fetch` و Bearer token دریافت می‌شود، نه `window.open` بدون header.

F022 اصلاح شد: Worker اکنون Notification را با dedup key ذخیره می‌کند، هویت Telegram کاربر را پیدا می‌کند، token ربات Main یا Store را انتخاب می‌کند، پیام را از طریق Telegram Bot API می‌فرستد، وضعیت sent/skipped/failed را ثبت می‌کند و failure را به outbox retry برمی‌گرداند. اجرای مجدد برای notification ارسال‌شده duplicate نمی‌فرستد.

F023 اصلاح شد: شمارنده‌های واقعی برای requestهای HTTP، نتیجه outbox و ارسال Telegram اضافه شد و endpoint متنی `/metrics` آن‌ها را در قالب Prometheus برمی‌گرداند. این counters در مسیرهای API و Worker صدا زده می‌شوند، نه فقط به‌صورت کد بلااستفاده.

compile/AST، syntax اسکریپت‌ها و assertionهای source موفق شدند. اجرای واقعی Telegram، Redis/ARQ، PostgreSQL و Prometheus در این محیط ممکن نیست.
