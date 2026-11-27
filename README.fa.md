# Melorin (ملورین)

[English](README.md)

پلتفرم فروش و مدیریت VPN: فروشگاه اصلی، فروشگاه نمایندگان، ربات‌های تلگرام، پنل ادمین و API مرکزی (FastAPI، PostgreSQL، Redis؛ فرانت React). معماری Modular Monolith. **منتشر نشده است.**

## شروع سریع

پیش‌نیاز: Docker با Compose v2 (پروداکشن) یا Python 3.12 + Node 22 + PostgreSQL + Redis (توسعه).

پروداکشن (سرور تازهٔ Ubuntu 22.04+ / Debian 12+ با root و ۴ گیگ رم): یک خط؛ پرچم‌ها (`install --yes`، `doctor`، `--external-proxy`) در docs/18.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/get.sh)
```

توسعه / از روی clone:

```bash
git clone https://github.com/archerhabibi/melorin-py.git && cd melorin-py
sudo bash melorin.sh install        # production install from a clone (docs/18)
# development
cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
alembic upgrade head && pytest -q
```

نصب کامل، استقرار، پشتیبان‌گیری و توسعهٔ محلی: [docs/18-OPERATIONS-DEPLOYMENT-DR.md](docs/18-OPERATIONS-DEPLOYMENT-DR.md). مهاجرت پایه: [docs/19-DATABASE-MIGRATIONS.md](docs/19-DATABASE-MIGRATIONS.md).

## نکات نصب

- سرور پیشنهادی: 4 GB RAM (بودجهٔ حافظهٔ compose برابر 3584 MiB). با پراکسی خارجی: `EXTERNAL_PROXY=true` و `127.0.0.1:18080`: `docker compose -f docker-compose.yml -f docker-compose.external.yml up -d --build`.
- مراحل دستی: `alembic upgrade head` سپس Admin bootstrap (ساخت اولین ادمین) و افزودن پنل‌ها/روش‌های پرداخت در Admin panel؛ ابزارهای اختیاری (S3، ورود Google/Telegram) در اسناد زیر.

- پایگاه داده: baseline مهاجرت تغییر کرد (جدول جدید `refund_operations`)؛ دیتابیس توسعهٔ قبل از انتشار را از نو و با `alembic upgrade head` روی پایگاه خالی بسازید.
- استرداد (Refund): استرداد درگاه یک گردش پایدار است (ثبت عملیات ← تماس با درگاه بدون قفل ← معکوس‌سازی دفتر کل). `refund_recovery_job` موارد نیمه‌کاره را ترمیم می‌کند و روش‌های بدون استرداد خودکار (کارت‌به‌کارت) به `manual_review` می‌روند. جزئیات: [docs/15](docs/15-PAYMENTS-WALLET-FINANCE.md).
- گیت کیفیت: `make guards`. `npm audit` برای وابستگی‌های runtime روی `high` و برای ابزار توسعه روی `critical` مسدودکننده است (ADR-R2 در [docs/06](docs/06-ARCHITECTURE-DECISIONS.md)). E2E مرورگر یک job اجباری CI است.

## مستندات

همهٔ اسناد مرجع دوزبانه‌اند (ابتدا فارسی، سپس انگلیسی). نقطهٔ شروع: [docs/00-DOCUMENTATION-INDEX.md](docs/00-DOCUMENTATION-INDEX.md).

- [Index / فهرست](docs/00-DOCUMENTATION-INDEX.md)
- [Product / محصول](docs/01-PRODUCT-OVERVIEW.md)
- [Architecture / معماری](docs/05-SYSTEM-ARCHITECTURE.md)
- [Admin UI / پنل ادمین](docs/09-ADMIN-UI-ARCHITECTURE.md)
- [API](docs/11-API-CONTRACTS.md)
- [Security / امنیت](docs/12-SECURITY-AUTHORIZATION.md)
- [Operations / عملیات](docs/18-OPERATIONS-DEPLOYMENT-DR.md)
- [Database / پایگاه داده](docs/19-DATABASE-MIGRATIONS.md)
- [Testing / تست](docs/20-TESTING-QUALITY-RELEASE.md)
- [Roadmap & debt / نقشه راه](docs/21-ROADMAP-TECHNICAL-DEBT.md)

فایل‌های `docs/STATUS.md` و `docs/API.md` تولیدشده‌اند (`make docs`).

## مشارکت

[CONTRIBUTING.md](CONTRIBUTING.md). نسخهٔ کامل قبلی README در [docs/01-PRODUCT-OVERVIEW.md](docs/01-PRODUCT-OVERVIEW.md) حفظ شده است.
