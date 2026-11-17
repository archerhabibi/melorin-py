# TODO — اجرای گزارش ممیزی (branch: fix/report-implementation)

ترتیب دسته‌ها: امنیت/پایداری > باگ/مالی > معماری > تست/CI > مستندات.
هر دسته یک commit و یک push. وضعیت: `[x]` انجام شد، `[ ]` باقی‌مانده، `[~]` بخشی/نیازمند محیط واقعی.

## دسته ۱ — امنیت و پایداری (M-04, M-11)
- [x] M-04 Rate limiter محلی: سقف تعداد کلید + پاک‌سازی دوره‌ای + `time.monotonic()`
- [x] M-11 Health: `rate_limit` در production هنگام قطع Redis برابر `fail_closed`

## دسته ۲ — مالی / باگ (M-10, M-03)
- [x] M-10 جدول `refund_operations` (state machine، idempotency key یکتا، lease، تلاش، audit)
- [x] M-10 `refund_payment` دو‌فازی: commit قبل از Gateway، فراخوانی Gateway بیرون از تراکنش، فاز نهایی با ledger reversal یک‌بار
- [x] M-10 job بازیابی (lease منقضی → ادامه/manual_review)
- [x] M-03 تفکیک Refund واقعی Gateway از جبران دستی (manual_review به‌جای 500/NotImplemented)
- [x] تست‌ها: refund تکراری، شکست gateway، crash پس از gateway، lease

## دسته ۳ — معماری (M-06, M-12)
- [~] M-06 مهاجرت Store Web و Admin Web به `packages/api-client`: انجام نشد؛ تغییر گستردهٔ ۲۰۰+ فایل فرانت است و بدون E2E قابل اجرا (Chromium دانلود نشد) ریسک regress دارد. پیشنهاد: یک PR جدا، feature-by-feature.
- [x] M-12 ثبت تصمیم‌ها در ADR (refund، commission، FX، identity)

## دسته ۴ — تست / CI (M-05, M-01, M-02)
- [x] M-05 حذف `continue-on-error` از web-e2e
- [x] M-01 (STATUS.md از سورس بازتولید شد؛ gen_docs قبلاً وجود داشت) اسکریپت تولید آمار از سورس (بدون عدد دستی)
- [~] M-02 `gen_docs.py` همچنان برای OpenAPI اپ را import می‌کند؛ جداسازی شمارش‌های استاتیک انجام نشد (ریسک کم، ارزش پایین)

## دسته ۵ — مستندات
- [x] CHANGELOG (در `docs/06`، طبق سیاست مستندات؛ فایل ریشهٔ جدا ساخته نشد) + ADR-R1 + docs/15 + STATUS
- [ ] README: بدون تغییر (رفتار کاربری عوض نشده)

## نیازمند محیط واقعی (انجام نمی‌شود در این branch)
- M-08 تست Providerهای واقعی (Sanaei, PasarGuard, Telegram, Zarinpal sandbox, S3)
- M-09 شکست Deploy #128 (نیاز به لاگ GitHub Actions و SSH/secrets سرور)
- M-07 پروفایل dev/prod در Compose (ریسک بالا بدون Docker اجرا‌شده)
- تست PostgreSQL concurrency / Docker compose کامل / نصب تمیز Ubuntu

## باقی‌مانده از همین branch (دلیل)
- **push به GitHub**: پروکسی نشست اجازه نداد (`ریپو در مجموعهٔ مجاز session نیست`، add_repo نیازمند لینک حساب GitHub). commitها محلی‌اند؛ خروجی `melorin-report.patch`.
- **E2E (M-05)**: `continue-on-error` حذف شد ولی اجرای محلی ممکن نشد (نسخهٔ Chromium مطابق Playwright 1.64 دانلود نشد). اولین CI را بررسی کنید؛ اگر قرمز بود، spec را اصلاح کنید.
- **Migration روی PostgreSQL** (`tests/postgres/*`) و concurrency واقعی اجرا نشد (PostgreSQL/Docker در دسترس نبود).
- Reconciliation فعال با Gateway (استعلام وضعیت refund) نیازمند API واقعی درگاه است؛ فعلاً manual_review.
- تغییر Schema: baseline عوض شد (جدول جدید)؛ دیتابیس dev را از نو بسازید.
