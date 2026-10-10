# تکمیل F015 تا F018 ملورین

F015 اصلاح شد: تمدید اکانت نامحدود دیگر به محدود تبدیل نمی‌شود؛ snapshot قبل از تمدید داخل سفارش ذخیره می‌شود و refund تمدید، rollback امن زمان/ترافیک را از مسیر outbox و adapter انجام می‌دهد.

F016 اصلاح شد: نتیجه نامعلوم provider دیگر مستقیم شکست تلقی نمی‌شود؛ پس از Unknown، وضعیت پنل read-back می‌شود و اگر اکانت ساخته شده باشد سفارش completed می‌شود، وگرنه مسیر retry/manual review ادامه پیدا می‌کند.

F017 سخت‌سازی شد: پیش از delivery، DNS دوباره resolve و با resolution قبلی مقایسه می‌شود؛ تغییر IP یا نبود resolution باعث توقف ارسال می‌شود و redirect همچنان خاموش است. این کنترل ریسک rebinding را می‌بندد، هرچند اثبات کامل runtime به تست شبکه نیاز دارد.

F018 اصلاح شد: Zarinpal دیگر ارز Store را silently به IRR تبدیل نمی‌کند؛ برای currency غیر IRR با خطای permanent رد می‌شود و callback آن نیز موفقیت جعلی نمی‌دهد.

compile/AST، syntax اسکریپت‌ها و assertionهای چهار finding موفق شدند. اجرای واقعی PostgreSQL، provider، DNS و panel sandbox در این محیط ممکن نیست.
