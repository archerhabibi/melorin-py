# طراحی اتصال حساب‌ها (Person / Account / Login Identity)

نگاشت روی کد موجود: Person (جدید) ← Account = `users` ← Login Identity = `identities` (+ `person_id`, `status`).
- قوانین خالص: `melorin/domain/account_linking.py`؛ سرویس: `modules/identity/account_linking/`؛ migration: `0057_person_account_linking`.
- یک تلگرام فعال برای هر Person (ایندکس یکتای جزئی)؛ Google/Email نامحدود؛ هویتِ فعالِ Person دیگر هرگز بی‌صدا جابه‌جا نمی‌شود (conflict + تأیید کاربر/ادمین).
- اتصال هویت‌ها پول جابه‌جا نمی‌کند. یکپارچه‌سازی مالی (`consolidation`) جدا، idempotent، با preflight (بدهی/پرداخت و سفارش در جریان/ریسلر مسدودکننده)، انتقال دفترکل، wallet قدیمی `consolidated` و routing در `get_wallet`. کیف پول per-store می‌ماند (ایزولاسیون فروشگاه‌ها).
- تأیید ادمین برای انتقال مالی (`identity_consolidation_auto_approve` پیش‌فرض خاموش). audit فقط‌افزودنی (trigger دیتابیس).
- API: `/identity/*` (کاربر)، `/admin/identity/*`، `/internal/identity/telegram/status` (ربات).
- UI سایت: تب «اتصال حساب‌ها» در داشبورد (`dashboard/DashboardLinking.tsx`) و بخش صفحهٔ اصلی. دکمهٔ «اتصال حساب‌های من» در منوی اصلی ربات (`cmd_link_accounts`).
- Reauth: رمز فعلی، یا کد یک‌بارمصرف ایمیل برای حساب‌های بدون رمز (`account_linking/reauth.py`)؛ حساب بدون رمز و بدون ایمیل (فقط تلگرام/Google) فقط نشست دارد و گارد «آخرین روش ورود» برقرار است.
- تست‌ها: HTTP برای reauth/unlink و یکپارچه‌سازی، تست سرویس برای ایزولاسیون فروشگاه‌ها و حساب مدیر.
- باقی‌مانده: تأیید با توکن واقعی ربات/Google، و تصمیم محصولی برای حساب‌های بدون رمز و ایمیل.
