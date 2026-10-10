# تکمیل F010 تا F015 ملورین

F010 با idempotency محدود به Store برای سفارش و پرداخت، unique constraint دیتابیس، بازیابی race همزمان، قفل ردیف و ثبت intent پرداخت پیش از فراخوانی provider سخت‌سازی باقی ماند.

سخت‌سازی تکمیلی سطح reliability و امنیت را بست: claimهای Worker و Webhook اکنون lease ده‌دقیقه‌ای و مسیر recovery دارند، enqueue وبهوک پیش از insert در برابر duplicate امن است، refund تکراری با row lock به no-op موفق تبدیل می‌شود و تست‌های regression برای HMAC و replay timestamp، backoff محدود retry و رد آدرس‌های حساس SSRF اضافه شدند. مسیر delivery وبهوک همچنان redirect را خاموش، IPهای خصوصی resolve‌شده را قبل از ارسال بررسی، event ID را امضا و retry را محدود می‌کند و پس از شکست‌های متوالی endpoint را auto-disable می‌کند.

راستی‌آزمایی: compile و AST پایتون موفق بود. اجرای زنده PostgreSQL/Redis، npm، Docker، provider و receiver وبهوک در این محیط ممکن نبود؛ بنابراین شواهد runtime ادعا نمی‌شود.
