# راهنمای اتصال «ورود با گوگل» به ملورین

> نسخه‌ی انگلیسی: [GOOGLE-LOGIN-SETUP-EN.md](GOOGLE-LOGIN-SETUP-EN.md)

## خلاصه

از این نسخه، تنظیمات ورود با گوگل از **پنل ادمین ← تنظیمات ← ورود با گوگل** انجام می‌شود و در دیتابیس سرور ذخیره می‌شود.
دیگر لازم نیست `MELORIN_GOOGLE_CLIENT_ID` را در `.env` بگذارید و فروشگاه/پنل را دوباره build کنید.

ملورین از **Google Identity Services (توکن ID)** استفاده می‌کند، پس:

| مورد | لازم است؟ |
|---|---|
| Client ID | بله |
| Client Secret | **خیر** (هیچ رمزی از گوگل ذخیره نمی‌شود) |
| Authorized JavaScript origins | بله |
| Authorized redirect URIs | **خیر** (خالی بماند) |
| Scopeهای اضافه / فعال‌کردن API | **خیر** (فقط `openid email profile`) |

## پیش‌نیازها

- دامنه‌ی فروشگاه و پنل با **HTTPS** (فقط `localhost` استثناست).
- یک حساب گوگل برای ساخت پروژه در Google Cloud.
- سرور API باید به `https://oauth2.googleapis.com` دسترسی خروجی (پورت ۴۴۳) داشته باشد.
- آدرس‌های فروشگاه و پنل در `MELORIN_STORE_WEB_URL`، `MELORIN_PUBLIC_API_URL` و `MELORIN_CORS_ORIGINS` درست تنظیم شده باشند (پنل از همین‌ها فهرست Origin پیشنهادی را می‌سازد).

## مراحل در Google Cloud Console

1. **ساخت پروژه:** <https://console.cloud.google.com/projectcreate>
2. **صفحه‌ی رضایت** (Google Auth Platform ← Branding یا APIs & Services ← OAuth consent screen):
   - User type: **External**
   - نام برنامه، ایمیل پشتیبانی، ایمیل تماس توسعه‌دهنده
   - Authorized domains: دامنه‌ی اصلی فروشگاه
   - Scopeها را تغییر ندهید (`openid`, `email`, `profile`: نیاز به بازبینی گوگل ندارند)
   - **Publishing status را از Testing به In production ببرید.** در حالت Testing فقط Test users (حداکثر ۱۰۰ نفر) می‌توانند وارد شوند.
3. **ساخت Client:** Credentials ← Create credentials ← **OAuth client ID** ← Application type: **Web application**
   - **Authorized JavaScript origins:** هر آدرس را جدا و به شکل `https://دامنه[:پورت]` بنویسید. بدون مسیر، بدون `/` پایانی.
     مثال: `https://shop.example.com` و `https://admin.shop.example.com`
     (پنل ادمین همین فهرست را با دکمه‌ی کپی نشان می‌دهد.)
   - **Authorized redirect URIs:** خالی.
4. **Client ID** را کپی کنید: `123456789012-abc123def456.apps.googleusercontent.com`
   (اعمال تغییرات گوگل می‌تواند از چند دقیقه تا چند ساعت طول بکشد.)

## مراحل در ملورین

1. پنل ادمین ← **تنظیمات** ← کارت **ورود با گوگل**.
2. Client ID را بچسبانید. فرمت آن هم‌زمان بررسی می‌شود.
3. سوئیچ‌ها:
   - **فعال‌سازی ورود با گوگل** (کلید اصلی)
   - **ورود مشتریان (فروشگاه)**
   - **ورود ادمین (پنل)**
4. **ذخیره** ← **تست اتصال سرور به گوگل**.
5. دکمه‌ی «ورود با گوگل» بدون build مجدد ظاهر می‌شود.

## رفتار ورود

- **مشتری:** حساب جدید خودکار ساخته می‌شود. اگر ایمیل تأییدشده‌ی گوگل با ایمیلِ یک حساب موجود یکی باشد، به همان حساب وصل می‌شود؛ تداخل مبهم برای بررسی ادمین ثبت می‌شود (نه ادغام خودکار).
- **ادمین:** ایمیل حساب گوگل باید **دقیقاً برابر ایمیل ادمین** باشد و TOTP فعال باشد. ابتدا کد TOTP را در صفحه‌ی ورود وارد کنید، سپس «ورود با گوگل». گوگل هرگز TOTP را دور نمی‌زند.
- خاموش‌کردن «ورود ادمین» یا «ورود مشتریان» فوراً اثر می‌کند و ورود با رمز/تلگرام/ایمیل را تغییر نمی‌دهد.

## سازگاری با نسخه‌های قبل

- اگر قبلاً `MELORIN_GOOGLE_CLIENT_ID` را در `.env` داشتید، تا زمانی که چیزی در پنل ذخیره نکنید همان مقدار کار می‌کند (پنل «از متغیر محیطی» را نشان می‌دهد).
- با اولین «ذخیره» در پنل، مقدار پنل برتری دارد (حتی برای خاموش‌کردن).
- `VITE_GOOGLE_CLIENT_ID` فقط به‌عنوان جایگزین زمانی استفاده می‌شود که صفحه نتواند به API برسد.

## API

| مسیر | دسترسی | کار |
|---|---|---|
| `GET /api/v1/auth/google/config` | عمومی | `{enabled, client_id, admin_login, store_login}`؛ در حالت غیرفعال `client_id` خالی است |
| `GET /api/v1/admin/integrations` | ادمین | فیلد `google` (شامل `source` و `suggested_origins`) |
| `PUT /api/v1/admin/integrations/google` | ادمین | ذخیره‌ی `{enabled, client_id, admin_login, store_login}` |
| `POST /api/v1/admin/integrations/google/test` | ادمین | بررسی فرمت و دسترسی سرور به گوگل |

کدهای خطا: `GOOGLE_CLIENT_ID_INVALID`، `GOOGLE_CONFIG_INCOMPLETE`، `GOOGLE_NO_SURFACE`، `GOOGLE_DISABLED`، `GOOGLE_ADMIN_DISABLED`، `GOOGLE_STORE_DISABLED`، `GOOGLE_INVALID`.
هر تغییر و تست در لاگ ممیزی (`integration.google.updated` / `integration.google.tested`) ثبت می‌شود.

## عیب‌یابی

| علامت | علت محتمل |
|---|---|
| `origin_mismatch` | آدرس صفحه (http/https، www، پورت) دقیقاً در Authorized JavaScript origins نیست |
| «access blocked» / `access_denied` | برنامه هنوز Testing است یا کاربر Test user نیست |
| `invalid_client` | Client ID اشتباه یا حذف‌شده |
| دکمه دیده نمی‌شود | سوئیچ اصلی یا سوئیچ همان بخش خاموش است؛ Client ID خالی است؛ یا مسدودکننده/CSP اسکریپت `accounts.google.com/gsi/client` را بسته است |
| «توکن Google نامعتبر است» | Client ID ذخیره‌شده با پروژه‌ی صادرکننده‌ی توکن یکی نیست، یا ساعت سرور نادرست است |
| تست اتصال ناموفق | فایروال/DNS/پروکسی خروجی سرور به `oauth2.googleapis.com:443` |
| One Tap مدتی نمایش داده نمی‌شود | cooldown خودِ گوگل بعد از چند بار بستن؛ چند دقیقه صبر کنید |
