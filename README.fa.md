# ملورین (Melorin)

پلتفرم چندفروشگاهی فروش VPN: فروشگاه اصلی، نمایندگان با فروشگاه، دامنه و ربات تلگرام اختصاصی، خرید مبتنی بر کیف پول و ساخت خودکار سرویس روی پنل‌های Sanaei و PasarGuard. مستندات کامل انگلیسی در [README.md](README.md) است؛ این صفحه نصب، به‌روزرسانی، توسعه و قوانین کار را خلاصه می‌کند.

## اجزای سیستم

| جزء | مسیر | نقش |
|---|---|---|
| API هسته (`api`) | `apps/api/melorin` | FastAPI؛ تنها مالک PostgreSQL و همهٔ قوانین کسب‌وکار |
| Worker (`worker`) | `apps/api/melorin/worker` | ARQ + Redis: outbox، تلاش مجدد ساخت سرویس، انقضا، سلامت پنل‌ها، تطبیق، پشتیبان رمزنگاری‌شدهٔ روزانه |
| وب فروشگاه (`store_web`) | `apps/store-web` | ویترین مشتری، داشبورد، کنسول نماینده |
| پنل ادمین (`admin_web`) | `apps/admin-web` | پنل مدیریت |
| ربات اصلی (`telegram_main`) | `apps/telegram-main` | ربات تلگرام اصلی؛ فقط انتقال پیام، منطق در هسته |
| ربات‌های نماینده (`telegram_reseller`) | `apps/telegram-reseller` | یک پردازش برای همهٔ ربات‌های نماینده؛ هسته آن را هدایت می‌کند و با افزودن/ویرایش نماینده نیازی به ری‌استارت نیست |
| PostgreSQL 16 / Redis 7 | compose | مرجع مالی / صف، rate limit و heartbeat کارگر |
| Caddy | `infra/Caddyfile` | TLS و مسیریابی (پروفایل `local-proxy`؛ در حالت پراکسی خارجی خاموش است) |
| Prometheus + Alertmanager | `infra/` | متریک، قوانین هشدار و ارسال به تلگرام و/یا ایمیل |

وب‌ها و ربات‌ها هرگز به دیتابیس دست نمی‌زنند و قیمت‌گذاری، کیف پول، سفارش، پرداخت و ساخت سرویس را خودشان پیاده نمی‌کنند؛ همه از هسته می‌آید.

## 🚀 نصب سریع

**منابع پیشنهادی:** ۴ گیگ رم و ۲ هسته CPU · Ubuntu 22.04+ (مجموع سقف حافظهٔ کانتینرها ۳٫۵ گیگابایت است؛ راهنمای عملیات را ببینید)

### قبل از نصب این‌ها را آماده کنید

1. **دامنهٔ سایت فروش** (مثلاً `shop.example.com`) متصل به آی‌پی سرور (رکورد A)
2. **دامنهٔ ادمین** (مثلاً `admin.example.com`) متصل به آی‌پی سرور (رکورد A)
3. **ایمیل ادمین** (نام کاربری ورود ادمین اول)
4. **توکن ربات تلگرام** از @BotFather

پورت‌های **80 و 443 باید آزاد باشند** (گواهی TLS خودکار توسط Caddy گرفته می‌شود). چیز دیگری پرسیده نمی‌شود.

### یک‌خطی

با کاربر root روی سرور اجرا کنید:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/get.sh)
```

این دستور پروژه را در `/opt/melorin` قرار می‌دهد، دستور `melorin` را می‌سازد و منو را باز می‌کند.
گزینهٔ **1) Install** را بزنید؛ فقط **دامنهٔ فروش، دامنهٔ ادمین، ایمیل ادمین و توکن ربات** (ورودی مخفی) را می‌پرسد، اشاره‌کردن دامنه‌ها به سرور را بررسی می‌کند و بقیهٔ نصب خودکار انجام می‌شود.
در پایان رمز یک‌بارمصرف ادمین و seed مربوط به TOTP چاپ می‌شود؛ همان لحظه ذخیره‌اش کنید.

### منوی اسکریپت (`melorin.sh`)

بعد از نصب، منو را هر زمان با دستور `melorin` باز کنید (یا داخل پوشهٔ پروژه: `bash melorin.sh`):

| گزینه | کار |
|---|---|
| `1` Install | نصب خاموش ← پرسیدن دامنهٔ فروش، دامنهٔ ادمین، ایمیل ادمین و توکن ربات |
| `2` Update | به‌روزرسانی کد، build، migration و ری‌استارت (`.env` حفظ می‌شود) |
| `3` Edit .env | ویرایش توکن ربات / دامنهٔ فروش / دامنهٔ ادمین یا باز کردن `.env` در ویرایشگر |
| `4` Web panel | آدرس فروشگاه و ادمین، health، ریست رمز ادمین، غیرفعال‌کردن محدودیت IP |
| `5` Service | وضعیت / استارت / توقف / ری‌استارت / لاگ کانتینرها |
| `6` Status | خلاصهٔ سلامت (نسخه، ربات، کانتینرها، API، دیسک، رم، کلید پشتیبان) |
| `7` Uninstall | حذف کامل (برای تأیید `DELETE` تایپ کنید) |
| `0` Exit | خروج |

میان‌بر بدون منو: `melorin status` ، `melorin update` ، `melorin restart` ، `melorin logs [service]` ، `melorin panel`.

متغیرهای اختیاری برای دستور یک‌خطی: `REPO_REF` (شاخه، تگ یا commit؛ پیش‌فرض `main` یعنی آخرین نسخه — برای کنترل سخت‌گیرانهٔ production یک تگ/commit بازبینی‌شده بدهید)، `REPO_URL` (مثلاً فورک private یا آدرس deploy key فقط‌خواندنی)، `APP_DIR` (پیش‌فرض `/opt/melorin`).

### نصب بدون تعامل (پیشرفته)

منو از `scripts/install_server.sh` استفاده می‌کند؛ برای اتوماسیون می‌توان آن را مستقیم اجرا کرد:

```bash
curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/scripts/install_server.sh -o install.sh
DOMAIN=shop.example.com ADMIN_DOMAIN=admin.example.com ADMIN_EMAIL=you@example.com REPO_REF=<commit-یا-تگ-بازبینی-شده> bash install.sh
```

در اجرای مستقیم حتماً `REPO_REF` را خودتان بدهید (خود اسکریپت یک pin پیش‌فرض داخلی دارد که لزوماً نسخهٔ موردنظر شما نیست). نصاب Docker را نصب می‌کند، پروژه را در `/opt/melorin` قرار می‌دهد، **توکن بات اصلی تلگرام** را می‌گیرد (منو خودش می‌دهد؛ در اجرای مستقیم با پرسش تعاملی یا `MAIN_BOT_TOKEN=...`)،
همهٔ secretها را خودکار می‌سازد، کلید پشتیبان‌گیری رمزنگاری‌شده را می‌سازد، migration می‌زند، سرویس‌ها را بالا می‌آورد و ثبت‌کنندهٔ خودکار تغییرات سرور (cron) را نصب می‌کند. اجرای دوباره‌اش بی‌خطر است.
اگر ریپو private است، اسکریپت را دستی به سرور ببرید و `REPO_URL` را با deploy key فقط‌خواندنی بدهید.

**ربات‌های نماینده به تنظیم زمان نصب نیاز ندارند.** کانتینر `telegram_reseller` همیشه روشن است؛ از هسته می‌پرسد کدام ربات‌ها را اجرا کند و تا وقتی نماینده‌ای نباشد بیکار می‌ماند. نماینده، دامنه و توکن رباتش را از پنل ادمین (نمایندگان) اضافه کنید؛ توکن‌ها رمزنگاری‌شده در دیتابیس ذخیره می‌شوند و ری‌استارت یا تغییر `.env` لازم نیست.

بعد از نصب:
1. با `https://admin.example.com` وارد شوید؛ با همان ایمیلی که هنگام نصب وارد کردید. نصاب رمز اولیه و seed مربوط به bootstrap را بعد از ساخت ادمین از `.env` حذف می‌کند؛ آن‌ها را همان موقع در جای امن نگه دارید. ورود ادمین با TOTP است (seed چاپ‌شده را به برنامهٔ احراز هویت اضافه کنید).
2. **فایل `/opt/melorin/secrets/backup/age-identity.txt` را حتماً جای امن و خارج از سرور کپی کنید.** بدون آن، پشتیبان‌ها قابل بازیابی نیستند.
3. پنل‌ها، پرداخت‌ها و سایر ارائه‌دهنده‌ها را از پنل ادمین طبق `docs/` تنظیم کنید.

### نصب پشت Reverse Proxy موجود

اگر پورت‌های ۸۰ یا ۴۴۳ قبلاً اشغال هستند، منو خودش تشخیص می‌دهد و این حالت را پیشنهاد می‌دهد (یا نصب را با `EXTERNAL_PROXY=true` اجرا کنید). در این حالت شاپ روی `127.0.0.1:18080`، ادمین روی `127.0.0.1:18081` و API روی `127.0.0.1:18000` قرار می‌گیرد؛ مسیرهای `/api/*` و `/health/*` را به API بدهید. دامنهٔ نمایندگان را هم به پورت فروشگاه بدهید و اگر پراکسی شما گواهی را on-demand می‌گیرد، با `GET 127.0.0.1:18000/api/v1/tls/ask?domain=<host>` کنترلش کنید (۲۰۰ = دامنهٔ ثبت‌شده، ۴۰۴ = رد). فایل `.env` ابتدا به‌صورت موقت ساخته و فقط پس از موفقیت اعتبارسنجی به‌صورت اتمی منتشر می‌شود.

### تنظیمات و نکات امنیتی

محدودیت IP ادمین اختیاری و به‌طور پیش‌فرض خاموش است و موقع نصب پرسیده نمی‌شود. برای فعال‌کردن: پنل ادمین ← تنظیمات ← یکپارچه‌سازی‌ها ← «دسترسی ادمین (محدودیت IP)». اگر قفل شدید: `docker compose exec -T api python -m melorin.cli disable-admin-ip-allowlist`. هنگام به‌روزرسانی در حالت پراکسی خارجی، همیشه از `docker compose -f docker-compose.yml -f docker-compose.external.yml up -d --build` استفاده کنید.

secretهای production را در فایل root-owned با سطح دسترسی `600` نگه دارید و ترجیحاً از secret file داکر یا سیستم‌عامل استفاده کنید؛ توکن را در خط فرمان وارد نکنید و هر توکن بات افشاشده را بچرخانید. اگر رمز ادمین گم شد، بدون ذخیره در history این دستور را اجرا کنید: `docker compose exec -T api python -m melorin.cli reset-admin-password admin@example.com`.

### اختیاری: SMTP، ورود با گوگل/تلگرام، S3

این‌ها **اختیاری** هستند و در زمان اجرا از پنل ادمین (تنظیمات ← یکپارچه‌سازی‌ها) فعال می‌شوند؛ بدون rebuild و بدون ویرایش `.env`:

- **SMTP:** بدون آن فقط ورود با کد ایمیلی کار نمی‌کند.
- **ورود با گوگل:** فقط Client ID لازم است. راهنما: [docs/GOOGLE-LOGIN-SETUP.md](docs/GOOGLE-LOGIN-SETUP.md).
- **ورود با تلگرام:** راهنما: [docs/TELEGRAM-LOGIN-SETUP.md](docs/TELEGRAM-LOGIN-SETUP.md) و [docs/TELEGRAM-WEB-LOGIN.md](docs/TELEGRAM-WEB-LOGIN.md).
- **پشتیبان S3:** پشتیبان رمزنگاری‌شده هر روز ساعت ۰۲:۰۰ UTC به‌صورت محلی ذخیره می‌شود و اگر S3 فعال باشد روی آن هم کپی می‌شود.

## به‌روزرسانی

**ساده‌ترین راه:** دستور `melorin` را بزنید و گزینهٔ **2) Update** را انتخاب کنید (کد جدید، build، migration و ری‌استارت؛ `.env` حفظ می‌شود). این روش همیشه روی خود سرور build می‌کند.

**خودکار و وابسته به CI (پیشنهادی):** workflow به‌نام `deploy.yml` **فقط بعد از یک اجرای موفق `CI` روی push به `main`** اجرا می‌شود و دقیقاً همان commitی را deploy می‌کند که CI تست کرده است. اجرای دستی (*Deploy ← Run workflow*) هم بررسی می‌کند که ref روی `main` باشد و CI سبز داشته باشد. این workflow اسکریپت `scripts/deploy.sh` را با SSH روی سرور اجرا می‌کند و آن اسکریپت:

1. قفل می‌گیرد و اگر فایل‌های tracked دستی ویرایش شده باشند، اجرا نمی‌شود؛
2. پیش از deploy یک پشتیبان رمزنگاری‌شدهٔ دیتابیس می‌گیرد (اگر شکست بخورد deploy متوقف می‌شود)؛
3. imageها را build می‌کند (یا در حالت registry می‌کشد)، `alembic upgrade head` می‌زند و سرویس‌ها را بالا می‌آورد؛
4. منتظر `/health/ready` (دیتابیس + Redis + heartbeat کارگر) و سالم‌شدن سرویس‌های اصلی می‌ماند؛
5. در صورت هر خطا **خودکار به commit قبلی برمی‌گردد**، دوباره build و بررسی می‌کند (کد خروج ۱ = rollback انجام شد، ۲ = rollback شکست خورد و دخالت دستی لازم است).

راه‌اندازی (یک‌بار):
1. روی سرور کاربری بسازید که مالک `/opt/melorin` و عضو گروه `docker` باشد (`adduser --disabled-password deploy` ، `usermod -aG docker deploy` ، `chown -R deploy:deploy /opt/melorin`).
2. یک جفت کلید SSH مخصوص بسازید، کلید عمومی را به `authorized_keys` همان کاربر اضافه کنید و host key را با `ssh-keyscan -t ed25519 -p 22 IP_سرور` بگیرید.
3. در GitHub (Settings ← Secrets and variables ← Actions) این secretها را بسازید: `DEPLOY_HOST`، `DEPLOY_USER`، `DEPLOY_PORT`، `DEPLOY_SSH_KEY` (کلید خصوصی) و `DEPLOY_KNOWN_HOSTS`. کلید خصوصی فقط همان‌جا بماند.
4. از تب Actions یک‌بار workflow را اجرا کنید و سبز بودنش را ببینید.

**حالت registry (اختیاری):** برای اینکه روی production هرگز build نشود، متغیر repository به‌نام `DEPLOY_IMAGE_REGISTRY` (مثلاً `ghcr.io/<owner>/melorin`) را در GitHub و همان مقدار را با نام `MELORIN_IMAGE_REGISTRY` در `.env` سرور بگذارید. جزئیات و رفتار fallback در [docs/RUNBOOK.md](docs/RUNBOOK.md) است.

**دستی (همان مسیر workflow):** `cd /opt/melorin && scripts/deploy.sh --ref <sha-یا-تگ>` — ref قدیمی‌تر یعنی rollback. rollback فقط **کد** را برمی‌گرداند؛ schema روی نسخهٔ جدید می‌ماند مگر اینکه `--db-downgrade` بدهید (فقط وقتی downgradeها واقعی‌اند).

## عملیات روزمره

با `melorin` (گزینه‌های ۵ و ۶) یا دستورهای زیر:

```bash
docker compose ps
docker compose logs --tail=200 api worker telegram_main telegram_reseller
curl https://shop.example.com/health/live     # /health/ready علاوه بر آن Redis و heartbeat کارگر را هم می‌سنجد
scripts/ops_log.sh                            # ثبت یادداشت (قبل / مشکل / اقدام / بعد) در لاگ سرور
```

- **هشدارها:** Prometheus و Alertmanager داخل compose هستند. دست‌کم یک گیرنده در `.env` تنظیم کنید: تلگرام (`ALERT_TELEGRAM_BOT_TOKEN` و `ALERT_TELEGRAM_CHAT_ID`) و/یا ایمیل (`ALERT_SMTP_*` و `ALERT_EMAIL_TO`)؛ وگرنه هشدارها ارزیابی می‌شوند ولی به جایی نمی‌رسند. `/metrics` توکن لازم دارد و روی دامنه‌های عمومی مسدود است.
- **پشتیبان:** روزانه، رمزنگاری‌شده، نگهداری ۳۰ روزه. workflow هفتگی `restore-drill.yml` جدیدترین پشتیبان خارج از سرور را در یک دیتابیس موقت بازیابی می‌کند تا کارکردش اثبات شود (تا وقتی secretهایش تنظیم نشود رد می‌شود). کلید age را **خارج از سرور** نگه دارید.
- **حافظه:** هر کانتینر سقف دارد و مجموع سقف‌ها ۳٫۵ گیگابایت است (دلیل پیشنهاد ۴ گیگ رم)؛ اگر سرویسی سقف نداشته باشد CI شکست می‌خورد.
- **حوادث** (PostgreSQL، Redis، پنل‌ها، درگاه‌ها)، چک‌لیست انتشار، rollback، دامنهٔ نمایندگان و زنجیرهٔ تأمین: [docs/RUNBOOK.md](docs/RUNBOOK.md). توجه: وقتی Redis در staging/production از کار افتاده باشد هیچ‌کس نمی‌تواند وارد شود (rate limit عمداً fail-closed است).

## ثبت تغییرات اجباری است
**هر تغییری — کد، تنظیمات یا کار روی سرور — باید ثبت شود**؛ و لازم نیست کسی یادش بماند، چون خودکار ثبت می‌شود. ولی دلیل را خودتان اضافه کنید:

- **کد (در git) ← `docs/CHANGE_LOG.md`:** روی هر push به `main` بات (workflow به‌نام `Changelog`) برای commitهای بدون ورودی ورودی می‌نویسد. در پیام commit بنویسید (`make setup-git` قالبش را فعال می‌کند):
  `Problem:` (مشکل) ، `Action:` (کاری که برای رفعش شد) ، `After:` (نتیجهٔ تأییدشده) ، و در صورت نیاز `Before:` و `Area:`.
- **کار روی سرور ← `var/ops-log.md`:** `scripts/ops_watch.sh` هر ۵ دقیقه تغییر commit، تغییر کلیدهای `.env` (فقط نام، نه مقدار)، دستکاری فایل‌ها و ری‌استارت کانتینرها را خودکار ثبت می‌کند؛ نتیجهٔ deploy هم ثبت می‌شود. دلیل را با `scripts/ops_log.sh` اضافه کنید.

هر ورودی شامل: **قبل**، **مشکل/خطا**، **اقدام برای رفع**، **بعد (نتیجهٔ تأییدشده)**، و چه کسی/چه زمانی. هرگز secret، توکن یا مقدار `.env` را در لاگ ننویسید.
این قانون برای همه است: اعضای تیم، پیمانکاران و دستیارهای هوش مصنوعی. جزئیات: [CONTRIBUTING.md](CONTRIBUTING.md).

## توسعهٔ محلی

پیش‌نیازها: Docker با Compose، Python 3.12، Node 22.

```bash
cp .env.example .env
# مقدار MELORIN_JWT_SECRET (حداقل ۳۲ کاراکتر)، MELORIN_ENCRYPTION_KEY (کلید Fernet) و مقادیر bootstrap ادمین را تنظیم کنید
make setup-git                    # اختیاری: قالب commit برای فیلدهای change log

# بدون Caddy؛ override پورت‌های loopback را باز می‌کند (فروشگاه 18080، ادمین 18081، API 18000)
docker compose -f docker-compose.yml -f docker-compose.external.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.external.yml run --rm api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.external.yml exec -T api python -m melorin.cli bootstrap   # ساخت ادمین اول (idempotent)
curl http://127.0.0.1:18000/health/live
```

مستندات API (`/docs`) فقط با `MELORIN_ENV=development` فعال است و Caddy آن را روی دامنه‌هایش پنهان می‌کند؛ پس مستقیم `http://127.0.0.1:18000/docs` را باز کنید. برای امتحان پراکسی داخلی در محیط محلی، stack را با `COMPOSE_PROFILES=local-proxy` بالا بیاورید.

اجرای بدون Docker (به PostgreSQL و Redis طبق `.env` نیاز دارد): `make api` ، `make worker` و برای وب `cd apps/store-web && npm ci && npm run dev` (برای `apps/admin-web` هم همین‌طور).

### بررسی‌ها

| دستور | کار |
|---|---|
| `make install-verify` | preflight تمیز محلی: ساخت `.venv`، نصب requirementهای قفل‌شده، import هستهٔ API و compile کد و تست‌ها |
| `make lint` | قراردادهای لایه‌بندی import-linter، `ruff check` و `ruff format --check` |
| `make test` | تست‌های API (به‌طور پیش‌فرض روی SQLite درون‌حافظه) |
| `make guards` | گاردهای ایستا: G001–G010، پیکربندی کیفیت، بودجهٔ حافظه/عملیات، به‌روز بودن اسناد تولیدشده |
| `make quality-gate` | کل gate محلی که CI هم اجرا می‌کند |
| `make web-lint` / `make web-format` | ESLint / Prettier برای هر دو وب |
| `make api-client` | به‌روزرسانی snapshot مربوط به OpenAPI و تولید/typecheck/تست `packages/api-client` |
| `make docs` | بازتولید `docs/STATUS.md` و جدول مسیرها در `docs/API.md` |
| `make migration-smoke` | ارتقای یک PostgreSQL به head و تأیید revision ثبت‌شده |

مسیرهای تست: مجموعهٔ پیش‌فرض روی SQLite اجرا می‌شود؛ با `TEST_PG_URL=postgresql+asyncpg://...` همان تست‌ها روی PostgreSQL (schema جدا برای هر تست، به‌علاوهٔ تست‌های همزمانی) اجرا می‌شوند؛ `pytest -m integration` به PostgreSQL و Redis نیاز دارد. وب‌ها Vitest دارند (`npm test`) و تست ربات‌ها در `apps/telegram-main/tests` است. CI برای پوشش تست backend یک کف دارد که فقط اجازهٔ افزایش دارد. جزئیات: [docs/09-Testing.md](docs/09-Testing.md).

تغییر دیتابیس به migration نیاز دارد (`make revision`)؛ CI روی یک PostgreSQL خالی `alembic upgrade head` و `alembic check` را اجرا می‌کند.

## ساختار پروژه

- `apps/api/melorin`: هستهٔ FastAPI، دامنهٔ خالص، kernel (مدل‌های ORM)، زیرساخت، ماژول‌های ویژگی، adapterهای کانال و worker. لایه‌بندی با import-linter اجباری است: `domain` ← `kernel` ← `core` ← `modules`.
- `apps/admin-web` و `apps/store-web`: دو وب‌اپ React + Vite + Tailwind با رابط فارسی راست‌به‌چپ، تم روشن/تیره و دیالوگ‌های دسترس‌پذیر.
- `apps/telegram-main` و `apps/telegram-reseller`: ربات اصلی و ناظر ربات‌های نماینده.
- `packages/api-client`: کلاینت تایپ‌شده که از snapshot مربوط به OpenAPI هسته (`openapi.json`) تولید می‌شود؛ اگر snapshot قدیمی باشد CI شکست می‌خورد. فعلاً وابستگی وب‌اپ‌ها نیست.
- `docs`: نیازمندی‌ها، معماری، طراحی، راهنمای عملیات، تصمیم‌ها و وضعیت تولیدشده.
- `infra`: Caddyfile، تنظیمات Prometheus و قوانین هشدار، Alertmanager.
- `scripts`: نصاب سرور، deploy با rollback، اسکریپت‌های پشتیبان و restore drill، ثبت خودکار تغییرات، گاردها و ابزارهای smoke/evidence.
- `.github/workflows`: `ci.yml` (audit وابستگی‌ها، بررسی قفل hash، گاردها، lint، تست‌ها، migration و E2E smoke، lint/test/build وب، بودجهٔ bundle، بررسی api-client، build imageها)، `deploy.yml`، `changelog.yml`، `pin-images.yml` (pin کردن imageهای پایه با digest) و `restore-drill.yml`.

## مستندات

| نیاز | مرجع |
|---|---|
| فهرست اسناد و نیازمندی‌ها | [docs/00-README.md](docs/00-README.md) |
| معماری، طراحی فنی، مدل داده، قراردادهای API | `docs/02` تا `docs/05`؛ فهرست مسیرهای تولیدشده: [docs/API.md](docs/API.md) |
| امنیت، مالی/سفارش/ساخت سرویس، عملیات و DR، تست، نقشهٔ راه | `docs/06` تا `docs/10` |
| راهنمای عملیات | [docs/RUNBOOK.md](docs/RUNBOOK.md) |
| تصمیم‌ها و موارد باز | [docs/DECISIONS.md](docs/DECISIONS.md) |
| سیاست مستندسازی | [docs/DOCUMENTATION-POLICY.md](docs/DOCUMENTATION-POLICY.md) |

هر وقت تنظیم، مسیر، مرحلهٔ نصب یا قاعدهٔ امنیتی عوض شد، این فایل، `README.md` و راهنمای عملیات را در همان تغییر به‌روز کنید و سپس `make docs` را اجرا کنید.

## وضعیت انتشار

این پروژه یک پلتفرم کامل و قابل اجراست، نه ادعایی بر اینکه اعتبارنامه‌های بیرونی، قرارداد درگاه‌ها، DNS، TLS، نسخهٔ پنل‌ها، تصمیم‌های مالی باز و تست بازیابی production کامل شده‌اند. وضعیت رسمی انتشار فقط در `docs/RELEASE-EVIDENCE-MATRIX.md` است و تا پیوست‌شدن شواهد اجرا و production «بسته» می‌ماند. اعداد اندازه‌گیری‌شده (head مایگریشن، تعداد API و تست) فقط در `docs/STATUS.md` (تولید خودکار) آمده است؛ گزارش‌های فازهای قبلی وضعیت جاری نیستند.
