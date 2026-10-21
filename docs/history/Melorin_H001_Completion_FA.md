# تکمیل H001: نصب و پیش‌نیازهای اجرای واقعی

## نتیجه
برای H001 یک مسیر نصب و preflight واقعی به خود پروژه اضافه شد. از این پس `make install-verify` یک virtualenv تمیز می‌سازد، dependencyهای API را از requirements پین‌شده نصب می‌کند، import واقعی Core را بررسی می‌کند و compile کد/تست‌ها را اجرا می‌کند.

## تغییرات
- `scripts/install_verify.sh`: ساخت `.venv`، نصب pinned requirements و اجرای preflight.
- `scripts/verify_runtime.py`: بررسی import دوازده dependency کلیدی و import واقعی `melorin.app` بدون تماس با provider.
- `aiosqlite==0.20.0` اضافه شد چون تنظیمات development از SQLite async استفاده می‌کند.
- CI اکنون preflight import را بعد از نصب dependency اجرا می‌کند.
- Makefile و README مسیر رسمی نصب/بررسی را ثبت کردند.

## اجرای این محیط
Python compileall، AST و syntax اسکریپت‌ها موفق شدند. اجرای install واقعی متوقف شد چون dependencyهای پروژه در محیط موجود نیستند و sandbox اینترنت ندارد؛ بنابراین ادعای نصب موفق، startup موفق، PostgreSQL/Redis یا Docker نمی‌کنم. در CI واقعی، همین preflight اکنون gate است.

## گام بعدی
در runner دارای دسترسی package registry اجرا شود:

```bash
make install-verify
python scripts/verify_runtime.py
```

سپس `docker compose build`, `alembic upgrade head`, API/Worker startup و health checks اجرا و log آن‌ها به‌عنوان evidence ذخیره شود.
