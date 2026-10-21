# تکمیل H003: اتصال واقعی وضعیت Backup به Admin Web

## نتیجه
H003 اصلاح شد. endpoint واقعی `GET /api/v1/admin/operations/backups` به Core Admin اضافه شد و Admin Web اکنون همان route موجود و احراز‌شده را مصرف می‌کند؛ دیگر 404 این endpoint باعث شکست `Promise.all` داشبورد نمی‌شود.

## پیاده‌سازی
- مدل `BackupRun` از دیتابیس خوانده می‌شود.
- خروجی به ۱۰۰ اجرای اخیر محدود است.
- فیلدهای status، location، size، details و created_at برمی‌گردند.
- endpoint فقط read-only و مخصوص Admin است.
- regression source test برای قرارداد route اضافه شد.

## شواهد
compileall، AST، syntax اسکریپت‌ها و route contract موفق شدند. اجرای واقعی FastAPI/PostgreSQL و build مرورگر در این محیط ممکن نیست؛ smoke test باید در CI/staging اجرا شود.
