# Google Sign-In setup / راه‌اندازی ورود با گوگل

Two sections: **English** first, then **فارسی** (same content).

## English — Connecting "Sign in with Google" to Melorin

### Summary

Google sign-in is now configured in **Admin panel → Settings → Google login** and stored on the server (database).
You no longer need `MELORIN_GOOGLE_CLIENT_ID` in `.env` or a rebuild of the storefront/admin images.

Melorin uses the **Google Identity Services ID-token flow**, so:

| Item | Needed? |
|---|---|
| Client ID | Yes |
| Client secret | **No** (no Google secret is stored) |
| Authorized JavaScript origins | Yes |
| Authorized redirect URIs | **No** (leave empty) |
| Extra scopes / enabling APIs | **No** (`openid email profile` only) |

### Prerequisites

- Storefront and admin served over **HTTPS** (`localhost` is the only exception).
- A Google account to create a Google Cloud project.
- The API server can reach `https://www.googleapis.com` (outbound 443) to fetch Google's public signing keys.
- `MELORIN_STORE_WEB_URL`, `MELORIN_PUBLIC_API_URL`, `MELORIN_CORS_ORIGINS` are correct (the panel derives the suggested origin list from them).

### Google Cloud Console

1. **Create a project:** <https://console.cloud.google.com/projectcreate>
2. **Consent screen** (Google Auth Platform → Branding, or APIs & Services → OAuth consent screen):
   - User type **External**; app name, support email, developer contact email.
   - Authorized domains: your main shop domain.
   - Leave scopes alone (`openid`, `email`, `profile` need no Google review).
   - **Move Publishing status from Testing to In production.** In Testing only listed test users (max 100) can sign in.
3. **Create the client:** Credentials → Create credentials → **OAuth client ID** → **Web application**.
   - **Authorized JavaScript origins:** one per row, `https://host[:port]`, no path, no trailing slash, e.g. `https://shop.example.com`, `https://admin.shop.example.com`. The admin panel lists them with copy buttons.
   - **Authorized redirect URIs:** leave empty.
4. Copy the **Client ID** (`123456789012-abc123def456.apps.googleusercontent.com`). Google changes can take minutes to hours to apply.

### In Melorin

1. Admin → **Settings** → **Google login** card.
2. Paste the Client ID (format is validated live).
3. Switches: **Enable Google sign-in** (master), **Customer login (storefront)**, **Admin login (panel)**.
4. **Save**, then **Test server → Google connectivity**.
5. The "Sign in with Google" button appears without a rebuild.

### How it works

- The button is **Google's official one** (`google.accounts.id.renderButton`): it follows the app theme (outline on light, `filled_black` on dark), is localised to Persian, and shows Google's own error messages. Melorin does not draw a lookalike button.
- Each page asks `GET /api/v1/auth/google/nonce` for a fresh nonce, passes it to Google, and the server also stores it in an httpOnly cookie. `POST /api/v1/auth/google` only accepts an ID token whose `nonce` equals that cookie, so a leaked or replayed token is useless. The cookie is consumed by a successful sign-in.
- The server verifies the ID token **locally** against Google's published keys (`https://www.googleapis.com/oauth2/v3/certs`, cached per Google's `Cache-Control`): RS256 signature, issuer, audience (= your Client ID), expiry and nonce.
- The sign-in popup needs the `Cross-Origin-Opener-Policy: same-origin-allow-popups` header (set in `infra/Caddyfile`). If you put another proxy in front, do not send `same-origin`.

### Sign-in behaviour

- **Customers:** a new account is created automatically. A verified Google email matching exactly one existing account links to it; ambiguous matches are queued for admin review, never auto-merged.
- **Admins:** the Google account's email must **equal the admin email** and TOTP must be enabled. Enter the TOTP code on the login page first (the Google button stays dimmed until a code is typed), then press "Sign in with Google". Google never bypasses TOTP.
- Turning off admin or customer login takes effect immediately and does not affect password/Telegram/email-code login.

### Backwards compatibility

- An existing `MELORIN_GOOGLE_CLIENT_ID` keeps working until something is saved in the panel (the panel shows "from environment").
- After the first save, the panel value wins (including turning Google off).
- `VITE_GOOGLE_CLIENT_ID` is only a fallback when the page cannot reach the API.

### API

| Route | Access | Purpose |
|---|---|---|
| `GET /api/v1/auth/google/config` | public | `{enabled, client_id, admin_login, store_login}`; `client_id` is empty while disabled |
| `GET /api/v1/auth/google/nonce` | public | `{nonce}` + httpOnly `melorin_gnonce` cookie (10 min, path `/api/v1/auth/google`) |
| `POST /api/v1/auth/google` | public | `{id_token, totp_code?}`; needs the nonce cookie |
| `GET /api/v1/admin/integrations` | admin | `google` block (with `source`, `suggested_origins`) |
| `PUT /api/v1/admin/integrations/google` | admin | save `{enabled, client_id, admin_login, store_login}` |
| `POST /api/v1/admin/integrations/google/test` | admin | format + server-to-Google reachability check |

Error codes: `GOOGLE_CLIENT_ID_INVALID`, `GOOGLE_CONFIG_INCOMPLETE`, `GOOGLE_NO_SURFACE`, `GOOGLE_DISABLED`, `GOOGLE_ADMIN_DISABLED`, `GOOGLE_STORE_DISABLED`, `GOOGLE_INVALID`, `GOOGLE_NONCE_INVALID`, `GOOGLE_UNREACHABLE`.
Changes and tests are audit-logged (`integration.google.updated` / `integration.google.tested`).

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| `origin_mismatch` | Page origin (http/https, www, port) is not exactly in Authorized JavaScript origins |
| "access blocked" / `access_denied` | App still in Testing, or user is not a test user |
| `invalid_client` | Wrong or deleted Client ID |
| Button missing | Master or per-surface switch is off, Client ID empty, or an ad-blocker/CSP blocks `accounts.google.com/gsi/client` |
| "Google token invalid" | Saved Client ID differs from the project that issued the token, or the server clock is wrong |
| "Session expired, try again" (`GOOGLE_NONCE_INVALID`) | The page was open > 10 min, cookies are blocked, or a proxy strips `Set-Cookie`; press the button again |
| Popup opens then nothing happens | `Cross-Origin-Opener-Policy: same-origin` is being sent by a proxy in front of the site |
| Connectivity test fails | Server firewall/DNS/egress proxy blocks `www.googleapis.com:443` |

## فارسی — راهنمای اتصال «ورود با گوگل» به ملورین

### خلاصه

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

### پیش‌نیازها

- دامنه‌ی فروشگاه و پنل با **HTTPS** (فقط `localhost` استثناست).
- یک حساب گوگل برای ساخت پروژه در Google Cloud.
- سرور API باید به `https://www.googleapis.com` دسترسی خروجی (پورت ۴۴۳) داشته باشد تا کلیدهای عمومی امضای گوگل را بگیرد.
- آدرس‌های فروشگاه و پنل در `MELORIN_STORE_WEB_URL`، `MELORIN_PUBLIC_API_URL` و `MELORIN_CORS_ORIGINS` درست تنظیم شده باشند (پنل از همین‌ها فهرست Origin پیشنهادی را می‌سازد).

### مراحل در Google Cloud Console

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

### مراحل در ملورین

1. پنل ادمین ← **تنظیمات** ← کارت **ورود با گوگل**.
2. Client ID را بچسبانید. فرمت آن هم‌زمان بررسی می‌شود.
3. سوئیچ‌ها:
   - **فعال‌سازی ورود با گوگل** (کلید اصلی)
   - **ورود مشتریان (فروشگاه)**
   - **ورود ادمین (پنل)**
4. **ذخیره** ← **تست اتصال سرور به گوگل**.
5. دکمه‌ی «ورود با گوگل» بدون build مجدد ظاهر می‌شود.

### نحوه‌ی کار

- دکمه، **دکمه‌ی رسمی خودِ گوگل** است (`google.accounts.id.renderButton`)؛ با تم برنامه هماهنگ می‌شود (روشن: outline، تیره: `filled_black`)، فارسی است و خطاهای خودِ گوگل را نشان می‌دهد. ملورین دکمه‌ی تقلیدی نمی‌کشد.
- هر صفحه از `GET /api/v1/auth/google/nonce` یک nonce تازه می‌گیرد و به گوگل می‌دهد؛ سرور هم همان را در کوکی httpOnly نگه می‌دارد. `POST /api/v1/auth/google` فقط توکنی را می‌پذیرد که `nonce` آن با کوکی برابر باشد؛ پس توکنِ لو رفته یا تکرارشده بی‌فایده است. ورود موفق کوکی را مصرف می‌کند.
- سرور توکن را **محلی** و با کلیدهای عمومی گوگل (`https://www.googleapis.com/oauth2/v3/certs` با کش طبق `Cache-Control`) راستی‌آزمایی می‌کند: امضای RS256، issuer، audience (= Client ID شما)، انقضا و nonce.
- پنجره‌ی ورود گوگل به هدر `Cross-Origin-Opener-Policy: same-origin-allow-popups` نیاز دارد (در `infra/Caddyfile` تنظیم شده). اگر پروکسی دیگری جلوی سایت دارید، `same-origin` نفرستید.

### رفتار ورود

- **مشتری:** حساب جدید خودکار ساخته می‌شود. اگر ایمیل تأییدشده‌ی گوگل با ایمیلِ یک حساب موجود یکی باشد، به همان حساب وصل می‌شود؛ تداخل مبهم برای بررسی ادمین ثبت می‌شود (نه ادغام خودکار).
- **ادمین:** ایمیل حساب گوگل باید **دقیقاً برابر ایمیل ادمین** باشد و TOTP فعال باشد. ابتدا کد TOTP را در صفحه‌ی ورود وارد کنید (تا وقتی کد وارد نشده دکمه‌ی گوگل کم‌رنگ و غیرفعال است)، سپس «ورود با گوگل». گوگل هرگز TOTP را دور نمی‌زند.
- خاموش‌کردن «ورود ادمین» یا «ورود مشتریان» فوراً اثر می‌کند و ورود با رمز/تلگرام/ایمیل را تغییر نمی‌دهد.

### سازگاری با نسخه‌های قبل

- اگر قبلاً `MELORIN_GOOGLE_CLIENT_ID` را در `.env` داشتید، تا زمانی که چیزی در پنل ذخیره نکنید همان مقدار کار می‌کند (پنل «از متغیر محیطی» را نشان می‌دهد).
- با اولین «ذخیره» در پنل، مقدار پنل برتری دارد (حتی برای خاموش‌کردن).
- `VITE_GOOGLE_CLIENT_ID` فقط به‌عنوان جایگزین زمانی استفاده می‌شود که صفحه نتواند به API برسد.

### API

| مسیر | دسترسی | کار |
|---|---|---|
| `GET /api/v1/auth/google/config` | عمومی | `{enabled, client_id, admin_login, store_login}`؛ در حالت غیرفعال `client_id` خالی است |
| `GET /api/v1/auth/google/nonce` | عمومی | `{nonce}` + کوکی httpOnly با نام `melorin_gnonce` (۱۰ دقیقه، مسیر `/api/v1/auth/google`) |
| `POST /api/v1/auth/google` | عمومی | `{id_token, totp_code?}`؛ به کوکی nonce نیاز دارد |
| `GET /api/v1/admin/integrations` | ادمین | فیلد `google` (شامل `source` و `suggested_origins`) |
| `PUT /api/v1/admin/integrations/google` | ادمین | ذخیره‌ی `{enabled, client_id, admin_login, store_login}` |
| `POST /api/v1/admin/integrations/google/test` | ادمین | بررسی فرمت و دسترسی سرور به گوگل |

کدهای خطا: `GOOGLE_CLIENT_ID_INVALID`، `GOOGLE_CONFIG_INCOMPLETE`، `GOOGLE_NO_SURFACE`، `GOOGLE_DISABLED`، `GOOGLE_ADMIN_DISABLED`، `GOOGLE_STORE_DISABLED`، `GOOGLE_INVALID`، `GOOGLE_NONCE_INVALID`، `GOOGLE_UNREACHABLE`.
هر تغییر و تست در لاگ ممیزی (`integration.google.updated` / `integration.google.tested`) ثبت می‌شود.

### عیب‌یابی

| علامت | علت محتمل |
|---|---|
| `origin_mismatch` | آدرس صفحه (http/https، www، پورت) دقیقاً در Authorized JavaScript origins نیست |
| «access blocked» / `access_denied` | برنامه هنوز Testing است یا کاربر Test user نیست |
| `invalid_client` | Client ID اشتباه یا حذف‌شده |
| دکمه دیده نمی‌شود | سوئیچ اصلی یا سوئیچ همان بخش خاموش است؛ Client ID خالی است؛ یا مسدودکننده/CSP اسکریپت `accounts.google.com/gsi/client` را بسته است |
| «توکن Google نامعتبر است» | Client ID ذخیره‌شده با پروژه‌ی صادرکننده‌ی توکن یکی نیست، یا ساعت سرور نادرست است |
| «نشست ورود منقضی شد» (`GOOGLE_NONCE_INVALID`) | صفحه بیش از ۱۰ دقیقه باز بوده، کوکی‌ها مسدودند یا پروکسی `Set-Cookie` را حذف می‌کند؛ دوباره روی دکمه بزنید |
| پنجره باز می‌شود ولی ورود کامل نمی‌شود | پروکسی جلوی سایت هدر `Cross-Origin-Opener-Policy: same-origin` می‌فرستد |
| تست اتصال ناموفق | فایروال/DNS/پروکسی خروجی سرور به `www.googleapis.com:443` |
