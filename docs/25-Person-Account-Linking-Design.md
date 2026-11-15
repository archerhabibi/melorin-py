# طراحی اتصال حساب‌ها (Person / Account / Login Identity)

نگاشت روی کد موجود: Person (جدید) ← Account = `users` ← Login Identity = `identities` (+ `person_id`, `status`).
- قوانین خالص: `melorin/domain/account_linking.py`؛ سرویس: `modules/identity/account_linking/`؛ migration: `0057_person_account_linking`.
- یک تلگرام فعال برای هر Person (ایندکس یکتای جزئی)؛ Google/Email نامحدود؛ هویتِ فعالِ Person دیگر هرگز بی‌صدا جابه‌جا نمی‌شود (conflict + تأیید کاربر/ادمین).
- اتصال هویت‌ها پول جابه‌جا نمی‌کند. یکپارچه‌سازی مالی (`consolidation`) جدا، idempotent، با preflight (بدهی/پرداخت و سفارش در جریان/ریسلر مسدودکننده)، انتقال دفترکل، wallet قدیمی `consolidated` و routing در `get_wallet`. کیف پول per-store می‌ماند (ایزولاسیون فروشگاه‌ها).
- تأیید ادمین برای انتقال مالی (`identity_consolidation_auto_approve` پیش‌فرض خاموش). audit فقط‌افزودنی (trigger دیتابیس).
- API: `/identity/*` (کاربر)، `/admin/identity/*`، `/internal/identity/telegram/status` (ربات).
- باقی‌مانده: UI سایت/ربات، تست‌های HTTP/مالی کامل‌تر، reauth قوی‌تر برای کاربران بدون رمز.
