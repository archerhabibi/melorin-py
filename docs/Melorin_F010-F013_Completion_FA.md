# تکمیل F010 تا F013 ملورین

F010 تکمیل شد: استفاده مجدد از Idempotency-Key با مبلغ، provider، purpose، محصول یا VPN account متفاوت دیگر silently پاسخ قبلی را برنمی‌گرداند و با خطای 409 رد می‌شود.

F011 تکمیل شد: callback پرداخت با row lock و parsing امن UUID اجرا می‌شود؛ شناسه خراب به خطای پایدار 404 تبدیل می‌شود و callback تکراری نمی‌تواند دوباره ledger را شارژ کند.

F012 تکمیل شد: نتیجه عملیات خارجی پرداخت شامل created یا create_failed و attempt ثبت‌شده نگهداری می‌شود تا خطای provider به وضعیت مبهم تبدیل نشود.

F013 تکمیل شد: enqueue وبهوک در برابر race همزمان duplicate-safe شد و conflict با savepoint مدیریت می‌شود تا rollback آن transaction مالی جاری را از بین نبرد؛ HMAC، event ID، retry محدود و replay window قبلی نیز حفظ شدند.

compile، AST، syntax اسکریپت‌ها و assertionهای کنترل‌های F010-F013 موفق شدند. اجرای واقعی PostgreSQL، Redis، provider و receiver وبهوک در این محیط ممکن نیست.
