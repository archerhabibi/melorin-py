# استراتژی تست و کیفیت
## انواع تست
Unit: pricing، Debt Limit، state transitions، Ledger و authorization. Integration: PostgreSQL، Redis، jobs، storage و adapters. Contract: Channel ↔ Core، Payment Adapter، Sanaei و PasarGuard. همچنین E2E، Security، Concurrency و Resilience.
## E2E اجباری
Registration/Login/Linking؛ Guest Checkout؛ callback پرداخت تکراری؛ Wallet؛ Main purchase؛ Reseller purchase؛ Debt Limit؛ provisioning success/failure/retry؛ refund و commission reversal؛ Test Account هم‌زمان؛ Ticket/attachment؛ notification retry؛ reconciliation؛ API credential disable/rotate؛ Backup/restore.
## Concurrency
دو خرید از یک Wallet، خرید هم‌زمان در آستانه Debt Limit، callback تکراری، Test Account موازی، دو Provisioning Retry هم‌زمان، Coupon محدود و redemption هم‌زمان، شارژ Store-scoped و تحویل/retry Webhook تست شوند. تست‌ها باید اثبات کنند که هر خرید فقط از Wallet همان Store برداشت می‌کند و هر Reseller فقط مشتریان/Couponهای Store خود را می‌بیند. DB constraints و idempotency جزو شواهد صحت هستند.
## CI Quality Gates
Lint/type checks، Unit/Integration tests، OpenAPI diff، migration test، dependency/security scan و build. Contract tests برای هر Adapter اجرا شوند.
## Definition of Done
وضعیت هر قابلیت: SPECIFIED → IMPLEMENTED → TESTED → PRODUCTION VERIFIED. عملیات مالی، Identity، Store authorization و Provisioning به E2E و Security test نیاز دارند.

## M7.7 — مسیر تست PostgreSQL / PostgreSQL test lane

- پیش‌فرض: تست‌های واحد روی SQLite درون‌حافظه (سریع و hermetic).
- با تنظیم `TEST_PG_URL=postgresql+asyncpg://melorin:test@localhost:5432/melorin` همان تست‌ها روی PostgreSQL اجرا می‌شوند؛ هر تست یک schema موقت و جدا می‌گیرد (`apps/api/tests/_db.py`).
- `tests/test_postgres_concurrency.py` فقط در این مسیر اجرا می‌شود: برداشت موازی بدون اضافه‌برداشت، و کلید idempotency یکسان که فقط یک‌بار ثبت می‌شود (`FOR UPDATE` در SQLite بی‌اثر است).
- در CI جاب `postgres-lane` این مسیر را اجرا می‌کند.
- Run locally: `cd apps/api && TEST_PG_URL=... pytest -q -m "not integration"`.
