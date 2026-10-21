# تکمیل F007 تا F010 ملورین

F007 سخت‌سازی شد: بکاپ PostgreSQL با `PGPASSFILE` اجرا می‌شود، رمز در argv قرار نمی‌گیرد، URL ناقص یا غیر PostgreSQL رد می‌شود و escaping امن برای colon/backslash در فایل password انجام می‌شود.

F008 تکمیل شد: recipient file غیرخالی اجباری است، بکاپ با age رمزنگاری می‌شود، checksum بلافاصله verify می‌شود، retention و off-host copy فعال است و اسکریپت restore با decrypt و `pg_restore --list` archive را بررسی می‌کند.

F009 دقیق‌تر شد: upload همچنان chunk-by-chunk و bounded است و WebP علاوه بر RIFF باید marker واقعی WEBP داشته باشد؛ در نتیجه MIME جعلی پذیرفته نمی‌شود.

F010 تکمیل شد: callback پرداخت با row lock وارد می‌شود، duplicate callback اعتبار مالی دوباره ایجاد نمی‌کند و نتیجه عملیات خارجی پرداخت در metadata ثبت می‌شود؛ خطای provider با attempt شکست‌خورده و وضعیت `create_failed` ثبت می‌شود تا عملیات pending مبهم نماند.

compile، AST، syntax اسکریپت و assertionهای کنترل‌های F007-F010 موفق شدند. اجرای واقعی PostgreSQL، age، Docker و provider در این محیط ممکن نیست.
