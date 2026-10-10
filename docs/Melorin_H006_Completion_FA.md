# تکمیل H006: refund واقعی پرداخت

## نتیجه
مسیر refund واقعی برای پرداخت‌های خارجی پیاده‌سازی شد. Zarinpal اکنون endpoint رسمی `payment/refund.json` را با `merchant_id`، `authority` و Bearer access token فراخوانی می‌کند؛ پاسخ‌های موفق provider با codeهای 100/101 پذیرفته می‌شوند و `ref_id/session` ثبت می‌شود.

## رفتار مالی
- فقط Payment موفق قابل refund است.
- Payment با row lock خوانده می‌شود و refund تکراری no-op است.
- عملیات خارجی ابتدا با وضعیت pending ثبت می‌شود.
- خطای provider در PaymentAttempt و metadata ثبت می‌شود.
- پس از موفقیت provider، ledger credit شارژ با کلید idempotent `payment:{id}:refund` reverse می‌شود.
- Payment به status `refunded` می‌رود و audit event ثبت می‌شود.
- Admin endpoint: `POST /api/v1/admin/payments/{payment_id}/refund`.

## محدودیت صادقانه
Manual Card refund هنوز provider خودکار ندارد و صریحاً نیازمند compensation/audit است. Zarinpal نیازمند `gateway.zarinpal.access_token`، merchant configuration و sandbox verification است. اجرای واقعی provider/PostgreSQL در این محیط ممکن نیست.

## شواهد
compileall، AST، shell syntax و source assertions موفق شدند. تست sandbox زرین‌پال و concurrency واقعی هنوز باید در CI/staging اجرا شود.
