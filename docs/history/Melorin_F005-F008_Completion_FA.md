# تکمیل F005 تا F008 ملورین

F005 اصلاح شد: CI ابتدا dependencyها را با نسخه‌های مستقیم pin‌شده resolve و lockfile را به‌صورت package-lock-only کامل می‌کند، سپس با `npm ci` نصب clean و build هر دو Web را اجرا می‌کند. Dockerfileهای Web نیز dev dependency لازم برای build را نصب می‌کنند.

F006 سخت‌تر شد: staging و production رمز ضعیف دیتابیس یا bootstrap admin را رد می‌کنند و علاوه بر secretهای پایه، نبود backup recipient و off-host target رمزنگاری‌شده را نیز fail-closed می‌کنند.

F007 اصلاح شد: `pg_dump` دیگر URL حاوی رمز را در argv نمی‌گیرد؛ اتصال با PGHOST/PGPORT/PGDATABASE/PGUSER و PGPASSFILE انجام می‌شود.

F008 تکمیل شد: بکاپ رمزنگاری‌شده، checksum و verify، retention، کپی off-host و اسکریپت مستقل بررسی restore archive با `pg_restore --list` اضافه شدند.

compile/AST، syntax اسکریپت‌ها، بررسی lockfile و assertionهای CI موفق بودند. npm، Docker، PostgreSQL و age در این محیط برای اجرای زنده موجود نیستند.
