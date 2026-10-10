# مشخصات کانال‌ها
## Admin Panel
مدیریت Users/Identities/Stores/Resellers، درخواست نمایندگی، Product/Categories/availability/pricing، Server/Panel/health، Orders/Payments/Refunds/Wallet/Ledger، Debt Limit، VPN Accounts، Retry/Manual Review، Referral/Commission، Test policies، Ticket/attachments، Notifications/Telegram Topics، API credentials، Feature Flags، Maintenance/Emergency، Audit، security events، backup status، health و reports/export. فقط API مرکزی؛ 2FA/IP restriction قابل تنظیم؛ عملیات حساس Audit شوند.
## Store Website
صفحات معرفی، سرویس، آموزش، FAQ، قوانین؛ catalog/checkout/order status؛ Guest Checkout؛ Google/Email login؛ داشبورد سفارش‌ها، VPN accounts، Wallet، تراکنش‌ها و Referral شخصی؛ Telegram linking؛ Ticket و Web Notification. هر خرید فقط با Wallet همان Store نهایی می‌شود؛ درگاه فقط برای شارژ Wallet استفاده می‌شود. هر Store ارز و مقصد پرداخت/تنظیمات شارژ خودش را دارد. Coupon در رابط نمایش داده می‌شود اما اعتبارسنجی و انتخاب نهایی فقط در Core است. CMS/Blog آینده. منطق کسب‌وکار فقط در Core.
## Main Telegram Bot
خرید، استعلام/تمدید، Wallet/شارژ، حساب کاربری و سفارش‌ها، قوانین/آموزش، Referral، Ticket، Test Account، مدیریت اکانت‌های خود کاربر و اعلان‌ها. عملیات Admin ندارد.
## Reseller Bot
فروش محصولات مجاز، مدیریت مشتریان عضو Store خودش، Customer Price، گزارش فروش، Wallet/debt status، شارژ Wallet مشتریان خودش در Store خودش، Couponهای همان Store، Branding/messages، هشدار Debt و اعلان‌های Store خودش. مشتری باید برای خرید در همان Store عضویت داشته باشد؛ تمام سفارش‌ها از Wallet همان Store پرداخت می‌شوند و شارژ به مقصد پرداخت همان فروشنده هدایت می‌شود. Token رمزنگاری‌شده؛ دسترسی مستقیم به Server/Panel و داده دیگر Resellerها ممنوع.
## Reseller API
`/api/v1`، credential lifecycle، scopes، rate limit، audit، Store isolation و قابلیت disable توسط Admin. دسترسی عمومی گسترده تا تکمیل Threat Model غیرفعال بماند.
## Telegram Group Event Center
Group مستقل Admin و هر Reseller؛ Topics مانند Payments، Orders، Provisioning، Errors، Customers، Wallet، Security و System. Routing بر اساس StoreContext، retry/deduplication، عدم ارسال Secret یا داده غیرضروری. اختیارات تغییر Group/Topic در RBAC نهایی شود.

## Coupon Management
Admin می‌تواند Couponهای هر Store یا دامنه‌ای را که صریحاً مجاز کرده ایجاد و مدیریت کند. Reseller فقط Couponهای Store خودش را ایجاد/مدیریت می‌کند. UI می‌تواند quote/validation را درخواست کند، اما اعتبار نهایی، سقف مصرف، scope، سقف تخفیف و انتخاب Coupon فقط در Core است.
