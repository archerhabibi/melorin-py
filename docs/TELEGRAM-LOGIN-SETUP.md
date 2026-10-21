# Telegram login setup / راه‌اندازی ورود با تلگرام

Two sections: **English** first, then **فارسی** (same content).

## English — Telegram login setup (Admin panel → Settings → Telegram login)

Status: implemented · no new migration · code: `apps/api/melorin/modules/identity/telegram_oidc*.py`, `apps/api/melorin/modules/admin/integrations.py`, `apps/admin-web/src/TelegramLoginSettings.jsx`

### Two methods, one account

| | Method 1 — approve in the bot | Method 2 — direct login (OpenID Connect) |
|---|---|---|
| Customer experience | site → Telegram bot → pick a number → back | site → Telegram's official page → "Confirm" → back |
| Data needed from BotFather | **none** | Client ID + Client Secret |
| Phishing resistance | number matching + device/IP shown + "that was not me" | Telegram's consent screen + PKCE + state |
| Customer browser needs | only the Telegram app | reach `oauth.telegram.org` |
| Technical doc | `docs/TELEGRAM-WEB-LOGIN.md` | this document |

Both identify the customer by the **numeric Telegram ID** (`Identity(provider="telegram")`), so someone created through the bot or the Mini App signs in to the **same account** with either method. **Admins cannot sign in with Telegram** (`admin_use_panel`); they use password + TOTP.

With no configuration (an existing install after upgrading) the previous behaviour is kept: method 1 on, method 2 off, lifetime and number matching from `.env`. As soon as an admin saves in the panel, the panel value wins.

### Step by step

#### Method 1 — approve in the bot
1. Admin panel → **Settings** → "Login with Telegram" card.
2. Turn on the master switch, "Customer login" and "Method 1".
3. (Optional) keep number matching on and set the request lifetime (60–600 s).
4. **Save** → **Test connection** (works on the saved values: checks the main bot token with `getMe`, compares the username with the store, and fails when the store has no bot username - without it no login link can be built).

#### Method 2 — direct login
1. In Telegram open the [BotFather mini app](https://t.me/botfather?startapp) → pick the bot → **Bot Settings → Web Login** (older name: *Login Widget*) → **OpenID Connect**.
2. Under **Allowed URLs** register every URL the panel card lists (one per row, https, no trailing slash):
   - the store origin, e.g. `https://shop.example.com`
   - the callback, e.g. `https://shop.example.com/api/v1/auth/telegram/oidc/callback`
   - for each active reseller with its own domain, that origin and callback too (the panel lists them).
3. Copy the **Client ID** (a number = the bot ID = the part of the bot token before ":") and the **Client Secret**.
4. Keep the **signing algorithm** at `RS256` (default) or `ES256`. `EdDSA`/`ES256K` only allow the bare `openid` scope and return no user ID, so login cannot work with them.
5. In the panel turn on "Method 2", paste Client ID and Secret → **Save** → **Test connection**. The test also checks the store URL: it must be a public https address (not localhost) and the callback URL it shows must be registered in BotFather.
6. In a private window try store → "Log in" → "Direct login with Telegram".

> Melorin requests only `openid profile` (ID, name, username). It does **not** ask for the phone number or permission for the bot to message the user.

### Technical flow (method 2)

```mermaid
sequenceDiagram
    participant B as Browser
    participant C as Core API
    participant T as oauth.telegram.org
    B->>C: GET /auth/telegram/oidc/start
    C-->>B: 303 to T + signed cookie (state, nonce, PKCE verifier)
    B->>T: user signs in and confirms
    T-->>B: 302 to /callback?code&state
    B->>C: GET /callback (with cookie)
    C->>T: POST /token (Basic: Client ID/Secret + code_verifier)
    T-->>C: id_token
    C->>T: GET /.well-known/jwks.json (cached 1 h)
    C-->>B: 303 to /#/dashboard + refresh cookie
```

Security rules (all covered by `apps/api/tests/test_r01_telegram_login_settings.py`):

- `state`, `nonce` and the PKCE verifier live in a signed (HS256), HttpOnly, `SameSite=Lax`, 10-minute cookie; no database row is created. The cookie is cleared after every outcome. If `state` differs from the cookie the code is never exchanged and a `tg_oidc_state_mismatch` security event is recorded.
- The `id_token` signature is verified against Telegram's JWKS; only `RS256`/`ES256` are accepted (no algorithm confusion); `iss`, `aud` (= Client ID), `exp`, `iat` are required and, when Telegram echoes a `nonce`, it must match.
- The account key is the `id` claim (the real Telegram user ID), not `sub`; without `id` the login is refused so no duplicate accounts appear.
- The **Client Secret** is Fernet-encrypted, used server-side only and never returned to the browser or written to the audit log.
- Admins, disabled accounts, closed registration (new accounts only) and the emergency `bot` flag behave exactly like method 1.
- Responses are `Cache-Control: no-store`; no token ever appears in a URL (the session is handed over by the refresh cookie and `POST /auth/refresh`).

### API

| Route | Caller | Notes |
|---|---|---|
| `GET /api/v1/auth/telegram/config` | storefront (public) | `{bot_login, oidc_login}`; no Client ID/Secret |
| `GET /api/v1/auth/telegram/oidc/start?store_id=` | browser | redirect to Telegram; 20/min rate limit |
| `GET /api/v1/auth/telegram/oidc/callback` | Telegram → browser | code exchange, session; 30/min rate limit |
| `GET /api/v1/admin/integrations` | admin | `telegram` key (no secret, `client_secret_set` flag) |
| `PUT /api/v1/admin/integrations/telegram` | admin | save; `client_secret`: omitted/null = keep, `""` = clear |
| `POST /api/v1/admin/integrations/telegram/test` | admin | Discovery, JWKS, Client ID, credentials, `getMe` |

Storage: `SystemSetting` key `integration.telegram_login` (like Google/SMTP/S3; hidden from the generic `/admin/settings`).

### Error codes (`/?tg_error=…` on the storefront)

| Code | Meaning |
|---|---|
| `user_denied` | the user declined in Telegram |
| `session_expired` | flow cookie missing/expired (over 10 min, cookies blocked, different host) |
| `origin_mismatch` | the visited host differs from `MELORIN_STORE_WEB_URL` / the reseller domain |
| `unavailable` | method off or incomplete, store inactive, or emergency `bot` flag |
| `failed` | bad state, wrong Secret, invalid token, or missing `id` |
| `unreachable` | the server could not reach Telegram |
| `registration_closed` / `account_disabled` / `admin_use_panel` | account rules (same as method 1) |

### Upgrade and rollback

1. Apply the patch; **no migration** (one `SystemSetting` row is created on first save).
2. Restart `api` and `telegram_main`; rebuild `store_web` and `admin_web`.
3. Caddy/CSP is unchanged (the flow is pure redirects; no third-party script is loaded).
4. Rollback: revert the patch. The setting row is harmless and ignored.

## فارسی — راه‌اندازی ورود با تلگرام (پنل ادمین ← تنظیمات ← ورود با تلگرام)

وضعیت: پیاده‌سازی‌شده · بدون migration جدید · کد: `apps/api/melorin/modules/identity/telegram_oidc*.py`، `apps/api/melorin/modules/admin/integrations.py`، `apps/admin-web/src/TelegramLoginSettings.jsx`

### دو روش، یک حساب

| | روش ۱ — تأیید در ربات | روش ۲ — ورود مستقیم (OpenID Connect) |
|---|---|---|
| تجربهٔ مشتری | سایت ← ربات تلگرام ← انتخاب عدد ← برگشت | سایت ← صفحهٔ رسمی تلگرام ← «تأیید» ← برگشت |
| داده‌ی لازم از BotFather | **هیچ** | Client ID + Client Secret |
| ضدفیشینگ | تطبیق عدد + نمایش دستگاه/IP + «این من نبودم» | تأییدیهٔ رسمی تلگرام + PKCE + state |
| نیاز مرورگر مشتری | فقط اپ تلگرام | دسترسی به `oauth.telegram.org` |
| سند فنی | `docs/TELEGRAM-WEB-LOGIN.md` | همین سند |

هر دو روش کاربر را با **شناسهٔ عددی تلگرام** (`Identity(provider="telegram")`) می‌شناسند؛ یعنی مشتری‌ای که قبلاً با ربات یا Mini App ساخته شده، با هر دو روش به **همان حساب** وارد می‌شود. ورود **ادمین** از تلگرام وجود ندارد (`admin_use_panel`)؛ ادمین فقط با رمز + TOTP وارد می‌شود.

بدون هیچ تنظیمی (نصب موجود، بعد از به‌روزرسانی) رفتار قبلی حفظ می‌شود: روش ۱ روشن، روش ۲ خاموش، مدت اعتبار و تطبیق عدد از `.env`. به‌محض اینکه ادمین در پنل «ذخیره» بزند، مقدار پنل مقدم است.

### راه‌اندازی گام‌به‌گام

#### روش ۱ — تأیید در ربات
1. پنل ادمین ← **تنظیمات** ← کارت «ورود با تلگرام».
2. کلید اصلی و «ورود مشتریان» و «روش ۱» را روشن کنید.
3. (اختیاری) تطبیق عدد را روشن نگه دارید و مدت اعتبار (۶۰ تا ۶۰۰ ثانیه) را تنظیم کنید.
4. **ذخیره** ← **تست اتصال**. تست روی مقدار ذخیره‌شده کار می‌کند: توکن ربات اصلی را با `getMe` می‌سنجد، نام کاربری را با فروشگاه مقایسه می‌کند و اگر نام کاربری ربات روی فروشگاه خالی باشد خطا می‌دهد (بدون آن لینک ورود ساخته نمی‌شود).

#### روش ۲ — ورود مستقیم
1. در تلگرام [BotFather Mini App](https://t.me/botfather?startapp) را باز کنید ← ربات را انتخاب کنید ← **Bot Settings ← Web Login** (نام قدیمی‌تر: *Login Widget*) ← حالت **OpenID Connect**.
2. در **Allowed URLs** همهٔ آدرس‌هایی را که کارت پنل نشان می‌دهد ثبت کنید (هر ردیف جدا، https، بدون «/» پایانی):
   - origin فروشگاه، مثل `https://shop.example.com`
   - آدرس بازگشت، مثل `https://shop.example.com/api/v1/auth/telegram/oidc/callback`
   - برای هر نمایندهٔ فعال با دامنهٔ اختصاصی، origin و callback آن دامنه هم (در فهرست پنل می‌آید).
3. **Client ID** (عدد؛ همان شناسهٔ ربات = عدد قبل از «:» در توکن ربات) و **Client Secret** را کپی کنید.
4. **الگوریتم امضا** را روی `RS256` (پیش‌فرض) یا `ES256` نگه دارید. `EdDSA`/`ES256K` فقط scope پایهٔ `openid` می‌دهند و شناسهٔ کاربر را برنمی‌گردانند؛ با آن‌ها ورود کار نمی‌کند.
5. در پنل «روش ۲» را روشن کنید، Client ID و Secret را بچسبانید ← **ذخیره** ← **تست اتصال**. تست آدرس فروشگاه را هم می‌سنجد: باید https عمومی باشد (نه localhost) و همان آدرس بازگشتِ نشان‌داده‌شده در BotFather ثبت شده باشد.
6. در پنجرهٔ ناشناس از فروشگاه «ورود» ← «ورود مستقیم با تلگرام» را امتحان کنید.

> ملورین فقط `openid profile` درخواست می‌کند (شناسه، نام، نام‌کاربری). شمارهٔ تلفن و اجازهٔ پیام‌دادن ربات درخواست **نمی‌شود**.

### جریان فنی روش ۲

```mermaid
sequenceDiagram
    participant B as مرورگر
    participant C as Core API
    participant T as oauth.telegram.org
    B->>C: GET /auth/telegram/oidc/start
    C-->>B: 303 به T + کوکی امضاشده (state، nonce، PKCE verifier)
    B->>T: ورود و تأیید کاربر
    T-->>B: 302 به /callback?code&state
    B->>C: GET /callback (با کوکی)
    C->>T: POST /token (Basic: Client ID/Secret + code_verifier)
    T-->>C: id_token
    C->>T: GET /.well-known/jwks.json (کش یک‌ساعته)
    C-->>B: 303 به /#/dashboard + کوکی refresh
```

قواعد امنیتی (همه با تست پوشش داده شده‌اند: `apps/api/tests/test_r01_telegram_login_settings.py`):

- `state`، `nonce` و PKCE verifier در کوکی HttpOnly، `SameSite=Lax`، امضاشده (HS256) و ۱۰ دقیقه‌ای نگه‌داری می‌شوند؛ هیچ ردیف دیتابیسی ساخته نمی‌شود. کوکی بعد از هر نتیجه پاک می‌شود. اگر `state` با کوکی یکی نباشد، کد اصلاً مبادله نمی‌شود و رخداد امنیتی `tg_oidc_state_mismatch` ثبت می‌شود.
- امضای `id_token` با JWKS تلگرام بررسی می‌شود؛ الگوریتم‌های مجاز فقط `RS256`/`ES256` (ضد algorithm-confusion)؛ `iss`، `aud` (= Client ID)، `exp`، `iat` اجباری‌اند و در صورت بازگشت `nonce` باید با نشست یکی باشد.
- کلید حساب، claim `id` (شناسهٔ واقعی تلگرام) است، نه `sub`؛ اگر `id` نباشد ورود رد می‌شود تا حساب تکراری ساخته نشود.
- **Client Secret** با Fernet رمزنگاری و فقط سمت سرور مصرف می‌شود؛ هرگز به مرورگر یا لاگ Audit برنمی‌گردد.
- ادمین، حساب غیرفعال، ثبت‌نام بسته (فقط حساب جدید) و پرچم اضطراری `bot` مثل روش ۱ اعمال می‌شوند.
- پاسخ‌ها `Cache-Control: no-store` دارند و هیچ توکنی در URL نمی‌آید (نشست از کوکی refresh و `POST /auth/refresh` تحویل داده می‌شود).

### API

| مسیر | مصرف‌کننده | توضیح |
|---|---|---|
| `GET /api/v1/auth/telegram/config` | فروشگاه (عمومی) | `{bot_login, oidc_login}`؛ بدون Client ID/Secret |
| `GET /api/v1/auth/telegram/oidc/start?store_id=` | مرورگر | ریدایرکت به تلگرام؛ rate limit ‏۲۰/دقیقه |
| `GET /api/v1/auth/telegram/oidc/callback` | تلگرام ← مرورگر | مبادلهٔ کد، ساخت نشست؛ rate limit ‏۳۰/دقیقه |
| `GET /api/v1/admin/integrations` | ادمین | کلید `telegram` (بدون secret، با `client_secret_set`) |
| `PUT /api/v1/admin/integrations/telegram` | ادمین | ذخیره؛ `client_secret`: نبودن = نگه‌داشتن، `""` = حذف |
| `POST /api/v1/admin/integrations/telegram/test` | ادمین | Discovery، JWKS، Client ID، اعتبارنامه، `getMe` |

ذخیره‌سازی: `SystemSetting` با کلید `integration.telegram_login` (مثل Google/SMTP/S3؛ از `/admin/settings` عمومی پنهان است).

### کدهای خطا (`/?tg_error=…` در فروشگاه)

| کد | معنی |
|---|---|
| `user_denied` | کاربر در تلگرام رد کرد |
| `session_expired` | کوکی نشست نبود/منقضی شد (بیش از ۱۰ دقیقه، کوکی بسته، دامنهٔ متفاوت) |
| `origin_mismatch` | دامنهٔ بازدید با `MELORIN_STORE_WEB_URL`/دامنهٔ نماینده یکی نیست |
| `unavailable` | روش خاموش یا ناقص است، فروشگاه غیرفعال، یا پرچم اضطراری `bot` |
| `failed` | state نامعتبر، Secret اشتباه، توکن نامعتبر، یا نبود `id` |
| `unreachable` | سرور به تلگرام نرسید |
| `registration_closed` / `account_disabled` / `admin_use_panel` | قواعد حساب (مثل روش ۱) |

### به‌روزرسانی و بازگشت

1. اعمال پچ؛ **migration لازم نیست** (فقط یک ردیف `SystemSetting` ساخته می‌شود).
2. ریستارت `api` و `telegram_main`؛ build مجدد `store_web` و `admin_web`.
3. Caddy/CSP تغییر نمی‌کند (جریان کاملاً ریدایرکتی است؛ اسکریپت شخص ثالث لود نمی‌شود).
4. بازگشت: برگرداندن پچ. ردیف تنظیمات بی‌ضرر است و نادیده گرفته می‌شود.
