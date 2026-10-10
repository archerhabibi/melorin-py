# نقشه راه و تصمیم‌های باز
## فازها
0. تثبیت نیازمندی، ADRها، State Machineها و مدل Money/Ledger.
1. Foundation: repo/CI، Core، DB، Redis، Identity، StoreContext، Authorization، Audit.
2. Catalog/Pricing، Wallet/Ledger، Payment abstraction و کارت‌به‌کارت.
3. Order State Machine، Server/Panel registry، Sanaei/PasarGuard adapters، retry/manual review/reconciliation.
4. Admin Panel، Website/Guest Checkout، Main Bot، Reseller Store/Bot و linking.
5. Referral، Test Account، Ticket، notification topics، Reseller API و گزارش‌ها.
6. Production hardening، monitoring، backup/restore، security review و E2E.
## تصمیم‌های قطعی مالک محصول (ثبت‌شده در نسخه 1.1)
1. واحد پول برای هر Store قابل تنظیم است؛ Currency باید صریح در تمام اسناد مالی ذخیره شود.
2. Reseller متقاضی باید پیش از درخواست/فعال‌سازی، عضو و مشتری Main Store باشد.
3. مشتری Reseller، Wallet خود را در Store همان Reseller شارژ می‌کند؛ مقصد پرداخت باید متعلق به همان Store باشد.
4. تمام خریدها فقط با Wallet همان Store انجام می‌شوند؛ درگاه/پرداخت دستی فقط Wallet را شارژ می‌کند.
5. Reseller مجاز است Wallet مشتریان خودش را شارژ کند.
6. مدل کمیسیون/پاداش توسط Admin برای هر طرح قابل انتخاب است؛ انتساب معرف بر اساس اولین معرف ثبت‌شده است.
7. ایمیل تأییدشده منطبق می‌تواند برای اتصال خودکار هویت‌ها استفاده شود؛ موارد تکراری/متعارض باید برای بازبینی دستی گزارش شوند.
8. تغییر مالک VPN Account توسط Admin در V1 غیرمجاز است.
9. صف کارهای پس‌زمینه: ARQ + Redis.
10. RPO حداکثر 24 ساعت؛ RTO حداکثر 8 ساعت.
11. Reseller API در V1 پیاده‌سازی و فعال است.
12. Outgoing Webhook در V1 پیاده‌سازی می‌شود.
13. Coupon در V1: سازنده Admin یا Reseller مجاز؛ Store scope یا دامنه صریحاً مجازشده توسط Admin؛ Reseller فقط Store خودش؛ ترکیب به‌صورت پیش‌فرض ممنوع؛ Core یک Coupon معتبر را اعمال می‌کند؛ سقف تخفیف، اعتبار زمانی و سقف مصرف کلی/هر مشتری قابل تنظیم؛ اعتبارسنجی فقط در Core.
14. Debt limit به‌صورت مقدار مثبت ذخیره و خرید در `balance <= -debt_limit` متوقف می‌شود.

## تصمیم‌های باز باقی‌مانده
1. درگاه آنلاین V1 و روش دقیق تأیید کارت‌به‌کارت/پرداخت دستی.
2. روش ورود ایمیلی و سیاست یکتایی Email در سطح Platform.
3. مدل دقیق تمدید سرویس: بسته‌های ثابت یا مقادیر آزاد؛ اصل فعلی افزایش زمان و حجم حفظ می‌شود.
4. Nginx یا Caddy.
5. Local یا S3-compatible برای فایل‌ها.
6. JWT/Refresh Token یا Session سمت سرور.
7. Stack نهایی Monitoring، Logging و Error Tracking.
8. سیاست دقیق بازیافت کمیسیون در صورتی که کمیسیون قبلاً خرج شده باشد؛ پیشنهاد فعلی کسر از کمیسیون‌های آینده است.
9. چه کسی مقصد گروه/Topic تلگرام را پیکربندی کند و جریان تأیید آن.
10. قواعد نهایی برخورد با چند User دارای ایمیل تأییدشده یکسان و فرآیند بررسی دستی.
11. آیا پاداش معرفی اولیه جدا از کمیسیون خریدهای بعدی فعال است و مدل آن برای هر طرح چگونه انتخاب می‌شود.
12. سیاست دقیق شارژ دستی Wallet مشتری توسط Reseller (چه نقش‌هایی مجازند و چه نوع سند/تأییدی لازم است)؛ مجاز بودن قابلیت قطعی است.
13. نحوه نمایش نرخ تبدیل و عملیات میان Storeهایی که Currency متفاوت دارند؛ تبدیل خودکار بین ارزها ممنوع تا سیاست مشخص شود.

## اصل تصمیم
پاسخ کسب‌وکاری مالک محصول بر جزئیات فنی اولویت دارد. برای تصمیم فنی باز، ساده‌ترین گزینه امن V1 انتخاب و در ADR ثبت شود. Future-ready بودن به معنی پیاده‌سازی همه قابلیت‌ها در V1 نیست.
