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
- [~] M-06 مهاجرت به `packages/api-client`: در عمل از قبل تدریجی در جریان است (در admin-web هیچ `authFetch(` مستقیمی خارج از `api/api.ts` نیست؛ Payments, Orders, Identity, Panel Ops با `typedClient`/`getJson`؛ store-web از `createApiClient` برای خواندن‌های عمومی). باقی‌مانده: ~۶۷ فایل با prop `call` و مسیرهای پویا، که طبق ADR (r5–r8) endpoint به endpoint و با تست جدا مهاجرت می‌شوند؛ مهاجرت یک‌جا ریسک regress دارد و اینجا انجام نشد.
- [x] M-12 ADR-R1 (refund، commission، FX، identity)

## دسته ۴ — تست / CI (M-05, M-01, M-02)
- [x] M-05 حذف `continue-on-error` از web-e2e (روی CI سبز: ۲۴ passed)
- [x] M-01 STATUS.md از سورس بازتولید می‌شود (`gen_docs --check` پاس)
- [x] M-02 `gen_docs.py` پیام روشن «وابستگی‌ها را نصب کنید» می‌دهد؛ import اپ عمداً می‌ماند چون فهرست route از OpenAPI زنده خوانده می‌شود
- [x] CI quality: `npm audit` به runtime=high / dev=critical (ADR-R2) برای picomatch بدون نسخهٔ اصلاح‌شده

## دسته ۵ — مستندات
- [x] CHANGELOG.md (خلاصه) + ورودی تاریخ‌دار docs/06 + ADR-R1/R2 + docs/15 + STATUS
- [x] README.md / README.fa.md: baseline، refund، گیت کیفیت

## باقی‌مانده (نیازمند محیط واقعی یا تصمیم کسب‌وکاری)
- M-06 مهاجرت کامل فرانت‌ها (بالا) — PRهای کوچک endpoint-by-endpoint.
- M-07 پروفایل dev/prod در Compose: عمداً تغییر نکرد (`integration_smoke.sh` وجود prometheus/alertmanager را الزامی می‌داند؛ تغییر رفتار پیش‌فرض نیازمند تصمیم محصول است). استک کامل روی سرور واقعی با موفقیت بالا آمد.
- M-08 تست Provider واقعی (Sanaei, PasarGuard, Telegram, Zarinpal sandbox, S3): نیازمند کلید/پنل/sandbox.
- M-09 علت دقیق شکست Deploy #128: باید از لاگ همان run خوانده شود؛ پیش‌بررسی SSH/secrets اضافه شد تا از این پس علت در لاگ روشن باشد.
- Reconciliation فعال refund با درگاه (استعلام وضعیت): نیازمند API واقعی درگاه؛ فعلاً `manual_review`.

## انجام‌شده روی سرور واقعی (2026-11-18)
- [x] `tests/postgres` (۱۲ passed، شامل migration baseline و تست جدید هم‌زمانی refund)
- [x] Docker Compose از دیتابیس خالی + `scripts/e2e_smoke.py` ALL PASSED
- [x] load probe: 74 rps، p95 984ms، خطا ۰
