# تکمیل H002: explicit Alembic baseline

## نتیجه
H002 در source اصلاح شد. migration اولیه دیگر از convenience metadata creation یا حذف کامل metadata استفاده نمی‌کند. `upgrade()` اکنون از `CreateTable` و `CreateIndex` از طریق Alembic برای تولید DDL دیالکت‌محور استفاده می‌کند و downgrade مخرب همچنان عمداً مسدود است.

## گیت‌های اضافه‌شده
- `scripts/migration_smoke.sh`: اجرای `alembic upgrade head`، بررسی current/heads و verify نسخه ثبت‌شده در PostgreSQL.
- `make migration-smoke`: مسیر رسمی اجرای گیت.
- regression source test برای ممنوعیت migrationهای create/drop سراسری در baseline.
- README به‌روزرسانی شد.

## شواهد این محیط
shell syntax، compileall، AST و source gate موفق شدند. اجرای واقعی Alembic/PostgreSQL ممکن نیست چون dependencyهای ORM/Alembic و سرویس PostgreSQL در این محیط نصب/در دسترس نیستند. بنابراین H002 از نظر source اصلاح شده، اما fresh-install و upgrade واقعی هنوز باید در CI/staging اجرا و log شود.
