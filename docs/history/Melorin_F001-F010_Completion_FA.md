# تکمیل F001 تا F010 ملورین

## نتیجه
F001، F006، F007، F008، F009 و بخش دیتابیسی F010 در baseline تجمعی اصلاح شدند. F002 تا F005 به‌دلیل نبود سورس واقعی Store Web و Admin Web و lockfile در مخزن canonical، هنوز قابل تکمیل صادقانه نیستند؛ قرارداد Caddy آماده شده اما ادعای build فرانت‌اند ممکن نیست.

## اصلاحات انجام‌شده
- F001: build سرویس API و Worker از ریشه repository انجام می‌شود تا مسیرهای COPY درست باشند.
- F006: در staging/production رمز ضعیف دیتابیس و bootstrap admin رد می‌شود.
- F007: بکاپ با PGPASSFILE اجرا می‌شود و رمز در آرگومان process قرار نمی‌گیرد.
- F008: فایل بکاپ رمزنگاری‌شده، checksum، retention، کپی off-host اختیاری و قرارداد restore اضافه شد.
- F009: آپلود به‌صورت chunk محدود خوانده می‌شود، سقف حجم دارد و magic-byte بررسی می‌شود.
- F010: idempotency سفارش و پرداخت Store-scoped شده و با unique constraint و بازیابی IntegrityError در برابر درخواست همزمان محافظت می‌شود؛ intent قبل از فراخوانی provider ثبت می‌شود.

## راستی‌آزمایی
compile و AST پایتون و syntax اسکریپت بکاپ موفق بود. Docker، PostgreSQL، Redis، npm و تست واقعی provider/restore در این محیط موجود نبودند. برای پایان F002 تا F005 باید سورس واقعی Web وارد baseline شود.
