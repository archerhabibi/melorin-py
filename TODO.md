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
- [ ] M-06 قرارداد: بررسی استفادهٔ API client (بخشی؛ مهاجرت کامل دو فرانت‌اند در حد این branch ممکن نیست)
- [ ] M-12 ثبت تصمیم‌ها در ADR (refund، commission، FX، identity)

## دسته ۴ — تست / CI (M-05, M-01, M-02)
- [ ] M-05 حذف `continue-on-error` از web-e2e
- [ ] M-01 اسکریپت تولید آمار از سورس (بدون عدد دستی)
- [ ] M-02 جدا کردن شمارش‌های استاتیک از import اپ

## دسته ۵ — مستندات
- [ ] README / CHANGELOG / docs (15, 18, 19, 21, STATUS)

## نیازمند محیط واقعی (انجام نمی‌شود در این branch)
- M-08 تست Providerهای واقعی (Sanaei, PasarGuard, Telegram, Zarinpal sandbox, S3)
- M-09 شکست Deploy #128 (نیاز به لاگ GitHub Actions و SSH/secrets سرور)
- M-07 پروفایل dev/prod در Compose (ریسک بالا بدون Docker اجرا‌شده)
- تست PostgreSQL concurrency / Docker compose کامل / نصب تمیز Ubuntu
