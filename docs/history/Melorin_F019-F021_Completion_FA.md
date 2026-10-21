# تکمیل F019 تا F021 ملورین

F019 اصلاح شد: ایجاد intent برای manual card در Main Store بدون card number و holder معتبر رد می‌شود؛ برای gatewayها نیز مقصد معتبر مانند merchant_id یا api_key لازم است. Storeهای دیگر نیز همین کنترل مقصد را دارند.

F020 اصلاح شد: endpoint گزارش Admin اضافه شد و فروش فقط از Paymentهای `succeeded` محاسبه می‌شود؛ خروجی به تفکیک currency برمی‌گردد و مبلغ ارزهای مختلف با هم جمع نمی‌شوند.

F021 اصلاح شد: endpoint CSV سفارش‌ها با احراز هویت Admin اضافه شد و Admin Web به‌جای `window.open`، خروجی را با Bearer token fetch می‌کند و به‌صورت فایل دانلود می‌دهد؛ بنابراین 401 ناشی از حذف header رخ نمی‌دهد.

compile/AST و assertionهای source موفق شدند. اجرای واقعی PostgreSQL، مرورگر و API زنده در این محیط انجام نشد.
