# اتصال کانال به فروشگاه (Channel Binding)

> وضعیت: پیاده‌سازی‌شده روی `feat/channel-binding` (بالای `main` پس از ادغام ایزوله‌سازی). همه‌ی منطق در Core است؛ سایت و ربات فقط می‌فرستند و نمایش می‌دهند.
> پیش‌نیاز: `14-Store-Isolation-Design.md` (StoreScope). این سند «کاربر در کدام فروشگاه است» را قطعی می‌کند؛ StoreScope می‌گوید «در آن فروشگاه چه چیزی می‌بیند».

## ۱. مسئله
پس از ایزوله‌سازی، هر مسیر مشتری زیر `/stores/{store_id}/…` است، ولی توکن ورود **سراسری** بود و `store_id` از **مسیر** می‌آمد. پس:
1. توکنِ ورود روی سایت A روی `/stores/B/…` هم کار می‌کرد (کاربر فنی، توکن لورفته، اشکال در یک کانال) و عضویت در B هم **خودکار** ساخته می‌شد.
2. ثبت‌نام و رفرال از سایت نماینده به فروشگاه اصلی نسبت داده می‌شد (سایت `store_id` نمی‌فرستاد).
3. ورود Mini App با توکن ربات اصلی برای هر `store_id` معتبر بود.
4. ورود با کد ایمیل و ورود از ربات برای حساب ادمین، توکن «ادمین» می‌داد (بدون TOTP).
5. مسیرهای `/tickets/{id}`، `/me/referrals`، `/me/stores` به فروشگاه نشست وابسته نبودند.

## ۲. قانون
1. هر نشست از راه یک **کانال** باز می‌شود: `site` (وب‌سایت یک فروشگاه)، `bot` (ربات یک فروشگاه) یا `admin` (پنل ادمین). کانال چهارم، `api`، **کلید API نماینده** است: نشست و توکن ندارد ولی همین قانون را دارد (بند ۳-ب).
2. نشستِ `site`/`bot` به **دقیقاً یک فروشگاه** بسته است و Core خودش آن را تشخیص می‌دهد؛ کلاینت انتخاب نمی‌کند.
3. توکن فقط در همان فروشگاه کار می‌کند. فروشگاه دیگر ← `403 CHANNEL_MISMATCH` **پیش از هر کوئری** (برای شناسه‌ی موجود و ناموجود یکسان؛ عضویتِ ناخواسته هم ساخته نمی‌شود).
4. نشست `admin` فقط از ورود رمز+TOTP (یا Google+TOTP) پنل ادمین ساخته می‌شود و همه‌جا معتبر است. حساب ادمین از راه سایت/ربات/کد ایمیل فقط نشست **مشتری** می‌گیرد یا (کد ایمیل/ربات) `ADMIN_USE_PANEL` می‌خورد.
5. refresh همان کانال و همان فروشگاه را دوباره صادر می‌کند؛ نمی‌شود نشست را به فروشگاه دیگر برد.

## ۳. چطور کانال تشخیص داده می‌شود (`core/channel.py`)
| کانال | منبع حقیقت | بررسی‌ها |
|---|---|---|
| `site` | هاست مؤثر درخواست (`X-Forwarded-Host` فقط از proxy مورد اعتماد) | باید `Store.domain` یک فروشگاه یا هاست‌های فروشگاه اصلی (`store_web_url`/`public_api_url`/`domain`) باشد؛ هاست ناشناس ← `CHANNEL_UNKNOWN` (در development به main/`hint` برمی‌گردد). `store_id`ی که کلاینت می‌فرستد فقط می‌تواند با هاست **هم‌خوان** باشد. |
| `bot` | secret رانر + فروشگاهی که نام می‌برد | فروشگاه فعال، ربات روشن، و نوعِ رانر مجاز (`main`/`reseller`/`any`). Mini App: فروشگاهی که **همان توکن ربات** را دارد (بدون fallback به توکن ربات اصلی). |
| `admin` | `ADMIN_CHANNEL`، فقط در دو handler رمز+TOTP/Google+TOTP | — |
| `api` | خودِ **کلید** (`X-API-Key`)؛ فروشگاهِ کلید هنگام ساخت ثابت می‌شود | `core.channel.api_channel` (ترتیب بررسی در بند ۳-ب) |

### ۳-ب. کانال `api` (کلید API نماینده)
کلید، نه URL، فروشگاه را تعیین می‌کند؛ `store_id` مسیر فقط می‌تواند با آن **هم‌خوان** باشد و این مقایسه **پیش از خواندن هر سطر فروشگاه** انجام می‌شود (شناسه‌ی موجود و ناموجود یک پاسخ می‌گیرند؛ مثل `ensure_store`). ترتیب بررسی‌ها، همه در `core.channel.api_channel`:
1. کلید وجود دارد، `active` است و منقضی نشده ← وگرنه `401 API_UNAUTHORIZED`
2. فروشگاهِ کلید = `store_id` مسیر ← وگرنه `403 API_STORE_ISOLATION` (همان کد قبلی؛ قرارداد عمومی API حفظ شده)
3. IP مبدأ داخل `ip_allowlist` کلید (اگر تنظیم شده) ← وگرنه `403 API_IP_FORBIDDEN`؛ IPِ ناشناخته **رد** می‌شود (fail-closed)
4. scope لازمِ مسیر در کلید هست ← وگرنه `403 API_SCOPE_FORBIDDEN`
5. فروشگاه از نوع `reseller`، `api_enabled` روشن و `active` است ← وگرنه `403 API_DISABLED` / `403 STORE_SUSPENDED`

مسیرها فقط scope می‌خواهند: `Depends(api_access("catalog:read"))` (در `core/deps.py`) که `StoreContext` مالک را می‌دهد (مالکِ غیرفعال ← `API_DISABLED`). `SessionClaims` همچنان `chn=api` را رد می‌کند؛ کانال `api` هرگز در توکن نمی‌نشیند. نگهبان‌های `test_t01` حالا مسیرهای `/reseller-api` را «عمومی» نمی‌شمارند و وجود `api_store_context` روی هرکدام را اجبار می‌کنند. پس از پذیرفته‌شدن درخواست، `last_used_at` کلید ذخیره (commit) می‌شود، حداکثر یک‌بار در دقیقه برای هر کلید (نشست درخواست هر چیز commit‌نشده را rollback می‌کند و بیشتر مسیرهای API فقط می‌خوانند). متریک: `melorin_channel_rejected_total{reason=api_key_unknown|api_key_inactive|api_store_mismatch|api_ip|api_scope|api_disabled|api_store_suspended}`.

توکن دسترسی: `chn` و `sid` (`adm` برای سازگاری می‌ماند). توکن بدون اتصال معتبر ← `401 SESSION_UNBOUND`. refresh-token: ستون‌های `channel`/`store_id` (migration `0027`)؛ خانواده‌ی قدیمی (NULL) در rotate رد می‌شود و کاربر یک بار دوباره وارد می‌شود (پروژه هنوز release نشده).

## ۴. قاعده‌ی هر لایه
| لایه | وابستگی | قاعده |
|---|---|---|
| مشتری `/stores/{id}/…` | `StoreCtx` ← `ensure_store` | `sid == path` یا نشست admin |
| مالک نماینده | `OwnerCtx` ← `ensure_owner_store` | کانال خودِ آن فروشگاه، **یا** فروشگاه اصلی به‌عنوان hub ولی فقط برای فروشگاهی که کاربر واقعاً مالکش است |
| API نماینده `/reseller-api/v1/stores/{id}/…` | `api_access(scope)` ← `api_channel` | کلیدِ همان فروشگاه + IP + scope + فروشگاه فعال با API روشن |
| ادمین `/admin/*` | `AdminUser` ← `require_admin_session` | کاربر ادمین **و** نشست کانال admin (+TOTP، IP) |
| `/me/stores` | `CurrentAuth` | فروشگاه‌ها: فقط همان فروشگاه؛ main: خودش + فروشگاه‌های تحت مالکیت؛ admin: همه |
| `/tickets/{id}`، `/me/referrals` | `CurrentAuth` | فقط سطرهای همان فروشگاه نشست؛ staff فقط با نشست admin |
| درخواست نمایندگی | `main_session_user` | فقط نشست کانال فروشگاه اصلی |
| handoff ربات ← سایت | `create_web_handoff(store)` | توکن فقط روی دامنه‌ی همان فروشگاه کار می‌کند؛ بدنه‌ی `store_id` فقط می‌تواند با نشست هم‌خوان باشد |
| ورود با تلگرام از وب (device flow / OIDC) | `site_channel(hint)` | شروع و poll/callback هر دو روی هاست همان فروشگاه |

### رانرها (حداقل دسترسی)
`MELORIN_BOT_SERVICE_SECRET` برای هر دو رانر کار می‌کند (سازگار). اختیاری: `MELORIN_MAIN_BOT_SECRET` و `MELORIN_RESELLER_BOT_SECRET` (≥۳۲ نویسه، متفاوت از هم و از secret مشترک). رانر `main` فقط در فروشگاه اصلی نشست می‌سازد؛ رانر `reseller` فقط در نمایندگی‌ها و فقط او `GET /internal/reseller-bots` (توکن رمزگشایی‌شده‌ی ربات‌ها) را می‌خواند. وقتی هر دو تنظیم باشند Core secret مشترک را بازنشسته می‌کند و کانتینر هر رانر فقط secret خودش را دارد (docs/17، R06).

## ۵. تغییرات
* **کانال `api` (T03):** `core/channel.py` (`API`، `ApiAccess`، `api_channel`)، `core/deps.py` (`api_access`)، `core/proxy.py` (`ip_in_networks`)، `reseller/api_keys.py` (`authenticate` حذف شد؛ `hash_key` عمومی)، `reseller/router.py` (`_api_ctx` حذف شد). بدون migration و بدون تغییر در کدهای خطا یا مسیرها.
* **Core:** `core/channel.py` (جدید)، `core/deps.py` (`AuthSession`، `store_context`، `owner_store_context`، `require_admin_session`، `BotAuth`)، `core/security.py`، `identity/{router,service,models,schemas,telegram_web*,telegram_oidc_router}`، `tickets/router`، `referral/router`، `reseller/{router,bots}`، migration `0027_channel_binding`.
* **ربات اصلی:** `/link` علاوه بر کد، `store_id` ربات را می‌فرستد.
* **سایت/ادمین‌وب:** بدون تغییر؛ سایت از قبل `credentials: include` و refresh با کوکی دارد و Host را مرورگر می‌فرستد.
* **زیرساخت:** reverse proxy باید `Host` اصلی (یا `X-Forwarded-Host`) را به API برساند. Caddy و nginx موجود این کار را می‌کنند؛ دامنه‌ی هر نماینده باید در `Store.domain` ثبت شده باشد (همان شرط صدور TLS).
* **خطاهای تازه:** `SESSION_UNBOUND` (401)، `CHANNEL_MISMATCH`، `CHANNEL_UNKNOWN`، `CHANNEL_FORBIDDEN`، `CHANNEL_DISABLED` (403)؛ متریک `melorin_channel_rejected_total{reason}`.

## ۶. تست‌ها
* `tests/test_t01_channel_binding.py` (۲۷ تست): claimها و رد توکن بی‌اتصال/قدیمی/ادمینِ تنزل‌یافته؛ Host (`X-Forwarded-Host` فقط از proxy مورد اعتماد، هاست ناشناس، hint ناهم‌خوان)؛ نوع رانر و secretها؛ رد نشست A روی B پیش از کوئری و بی‌عضویت‌سازی؛ ادمین/مشتری؛ hub مالک؛ issue/rotate/handoff؛ و **نگهبان‌ها**: فهرست دقیقِ مسیرهای بدون نشست (مسیر جدید باز بدون بازبینی شکست می‌خورد)، هر مسیر `{store_id}` با وابستگی کانال، هر مسیر ادمین با `require_admin_session`، و `issue_tokens` فقط با کانال.
* `tests/test_t03_api_key_channel.py` (کانال `api`): اتصال کلید به فروشگاهش، رد کلید A روی B (برای فروشگاه موجود و ناموجود یکسان)، کلید نامعتبر/غیرفعال/ابطال‌شده/منقضی، چرخش کلید، scope، IP allowlist (fail-closed و تقدم بر scope)، API خاموش، فروشگاه معلق، مالک غیرفعال، و نگهبان: هر مسیر `/reseller-api` باید `api_store_context` داشته باشد.
* ۱۸ تست قدیمی با امضای جدید به‌روز شد؛ `tests/_chan.py` ابزار مشترک است.
* `scripts/e2e_smoke.py`: توکن مشتری روی فروشگاه دیگر ← ۴۰۳، `/me/stores` فقط فروشگاه خودش، ادمین با کد ایمیل ← `ADMIN_USE_PANEL`.
* نگهبان قدیمی `test_r01_store_isolation::_customer_routes` روی `app.routes` می‌گشت که در FastAPI فعلی `_IncludedRouter` است و مسیری نمی‌دید؛ نگهبان تازه از روترهای اصلی پیمایش می‌کند.

## ۷. انتشار
* پنجره‌ی ناسازگاری: همه‌ی کاربران یک بار دوباره وارد می‌شوند (توکن‌های قدیمی `SESSION_UNBOUND`). ربات‌ها هر پیام را دوباره login می‌کنند و بی‌اثر است. هم‌زمان deploy شود: API، ربات‌ها (برای `store_id` در `/link`)، سایت.
* بازگشت: `git revert` + `alembic downgrade 0026_merge_reseller_credit` (دو ستون nullable حذف می‌شود).
* قبل از deploy: دامنه‌ی تک‌تک نمایندگان در `Store.domain` درست باشد وگرنه ورود از آن سایت `CHANNEL_UNKNOWN` می‌دهد.

## ۸. باقی‌مانده
* بررسی کوپن (سقف استفاده‌ی هر کاربر) و ثبت رفرال (`attach`) از نظر هم‌پوشانی فروشگاه‌ها (تیکت و `/me/referrals` در این پچ بسته شد).
* (انجام شد در R06 - docs/17) secretهای جدای رانرها در compose/installer/update.
* (انجام شد در T03) اتصال کانال به کلید API نماینده.
* `rate_limit_per_minute` کلید ذخیره و نمایش داده می‌شود ولی هنوز اعمال نمی‌شود؛ اعمالش (با `core.ratelimit.hit`) نیازمند تصمیم درباره‌ی رفتار هنگام قطع Redis است.
