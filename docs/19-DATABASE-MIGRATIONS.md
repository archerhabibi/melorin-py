# پایگاه داده و مهاجرت‌ها / Database & Migrations

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** سیاست schema و baseline Alembic.

پروژه منتشر نشده است؛ مهاجرت‌های ۰۰۰۱ تا ۰۰۵۷ با یک baseline جایگزین شدند: `apps/api/alembic/versions/0001_initial_baseline.py`. این فایل schema کامل را روی پایگاه خالی می‌سازد: جدول‌ها/ایندکس‌ها از metadata مدل‌ها، sequenceهای `order_number_seq` و `ticket_number_seq`، trigger غیرقابل‌تغییر `account_link_audits` و دو seed پیش‌فرض `system_settings`. اعتبارسنجی: `alembic upgrade head` روی Postgres خالی، downgrade/upgrade مجدد و مقایسهٔ schema با مدل‌ها (صفر اختلاف). روش تغییر بعدی: مهاجرت جدید با `alembic revision --autogenerate` که از `0001_initial_baseline` ادامه می‌دهد. محدودیت: downgrade فقط برای توسعه است و مسیر ارتقا از پایگاه‌های قدیمیِ پیش از baseline پشتیبانی نمی‌شود (تصمیم صریح پیش از release).

## English section

**Purpose:** Schema policy and the Alembic baseline.

The project is unreleased, so migrations 0001-0057 were replaced by one baseline: `apps/api/alembic/versions/0001_initial_baseline.py`. It builds the full schema on an empty database: tables/indexes from the model metadata, the `order_number_seq` and `ticket_number_seq` sequences, the append-only trigger on `account_link_audits`, and the two default `system_settings` seeds. Validation: `alembic upgrade head` on empty Postgres, downgrade/upgrade again, and a schema-vs-models diff (zero differences). Future changes: new revisions via `alembic revision --autogenerate` on top of `0001_initial_baseline`. Limitation: downgrade is for development only and upgrading databases created before the baseline is intentionally unsupported (explicit pre-release decision).

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
