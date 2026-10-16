# امنیت، هویت و مجوزها
## اصول
Deny-by-default، least privilege، Core-enforced authorization و جداسازی StoreContext. پنهان‌کردن UI جایگزین Authorization نیست.
## Authentication
Telegram identity باید معتبرسنجی شود. Website از Google و/یا Email استفاده می‌کند؛ روش دقیق Email باز است. Token/session دارای expiry، refresh/rotation، logout/revoke و محافظت replay باشد. Account linking: پس از تأیید ایمیل، تطبیق ایمیل تأییدشده می‌تواند هویت‌ها را به User مرکزی متصل کند. هر تعارض، چند حساب محتمل یا وضعیت مبهم باید اتصال خودکار را متوقف کرده، رخداد قابل Audit ایجاد و برای بازبینی دستی گزارش شود.
ورود Website با تأیید در ربات تلگرام (Device Authorization با اتصال به مرورگر، تطبیق عدد و نمایش دستگاه/IP) در `docs/TELEGRAM-WEB-LOGIN.md` توصیف شده است؛ ادمین‌ها از این مسیر وارد نمی‌شوند.
## Authorization
- Admin: تمام Storeها.
- Reseller: فقط Store، مشتریان، گزارش و عملیات مجاز خودش.
- Customer: داده‌های خودش.
- API credential: scopes محدود و قابلیت disable/revoke.
تست IDOR و cross-store access اجباری.
## Secrets
Bot token، Panel credential و gateway secrets با encryption-at-rest؛ کلید رمزنگاری جدا از DB. TLS، rotation و masking در log الزامی. Backup رمزنگاری‌شده.
## Admin
2FA قابل فعال‌سازی و IP restriction اختیاری. Rate limit، anti-brute-force، expiry و ثبت تلاش ناموفق.
## Audit/Security Events
Append-only audit برای تغییرات مالی، هویت، قیمت، تنظیمات، API credential، refund، provisioning و emergency control. رویدادهای brute force، API abuse، token abuse، linking غیرعادی و تلاش cross-store باید alert شوند. Hash-chain یا export خارج سرور می‌تواند برای tamper evidence قوی‌تر افزوده شود.
## Coupon و Webhook Security
Coupon scope و quota در Core enforce شوند؛ هرگز به قیمت یا تخفیف ارسالی از Channel اعتماد نشود. Webhook خروجی با HMAC امضا، timestamp و شناسه رویداد یکتا ارسال شود؛ مقصدها allowlist/اعتبارسنجی شوند، SSRF کنترل شود، timeout و retry محدود باشد و secret امضا رمزنگاری‌شده نگهداری و قابل rotation باشد.
## Privacy
حداقل‌سازی داده شخصی، کنترل دسترسی به Email/Telegram ID/اطلاعات پرداخت، Terms/Privacy versioning و retention. اطلاعات مالی و Audit با حذف عادی User پاک نمی‌شوند.
