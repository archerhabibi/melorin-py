# ملورین (Melorin)

پلتفرم چندفروشگاهی فروش VPN. مستندات کامل انگلیسی در [README.md](README.md) است؛ این صفحه فقط نصب و قوانین کار را خلاصه می‌کند.

محدودیت IP ادمین اختیاری و به‌طور پیش‌فرض خاموش است و موقع نصب پرسیده نمی‌شود. برای فعال‌کردن: پنل ادمین ← تنظیمات ← یکپارچه‌سازی‌ها ← «دسترسی ادمین (محدودیت IP)». اگر قفل شدید: `docker compose exec -T api python -m melorin.cli disable-admin-ip-allowlist`. هنگام به‌روزرسانی در حالت پراکسی خارجی، همیشه از `docker compose -f docker-compose.yml -f docker-compose.external.yml up -d --build` استفاده کنید.
secretهای production را در فایل root-owned با سطح دسترسی `600` نگه دارید و ترجیحاً از secret file داکر یا سیستم‌عامل استفاده کنید؛ توکن را در خط فرمان وارد نکنید و هر توکن بات افشاشده را بچرخانید. اگر رمز ادمین گم شد، بدون ذخیره در history این دستور را اجرا کنید: `docker compose exec -T api python -m melorin.cli reset-admin-password admin@example.com`.

## نصب روی سرور

**پیش‌نیاز:** سرور اوبونتو با دسترسی root، دو دامنه (فروشگاه و ادمین) که به سرور اشاره کنند، و **آزاد بودن پورت 80 و 443** (گواهی TLS خودکار توسط Caddy گرفته می‌شود).

```bash
curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/scripts/install_server.sh -o install.sh
DOMAIN=shop.example.com ADMIN_DOMAIN=admin.example.com ADMIN_EMAIL=you@example.com bash install.sh
```

نصاب Docker را نصب می‌کند، پروژه را در `/opt/melorin` قرار می‌دهد، **توکن بات اصلی تلگرام** را می‌پرسد (یا `MAIN_BOT_TOKEN=...`)،
همهٔ secretها را خودکار می‌سازد، کلید پشتیبان‌گیری رمزنگاری‌شده را می‌سازد، migration می‌زند، سرویس‌ها را بالا می‌آورد و ثبت‌کنندهٔ خودکار تغییرات سرور (cron) را نصب می‌کند. اجرای دوباره‌اش بی‌خطر است.
بات‌های ریسلر پیش‌فرض خاموش‌اند (`COMPOSE_PROFILES=reseller`). اگر ریپو private است، اسکریپت را دستی به سرور ببرید و `REPO_URL` را با deploy key فقط‌خواندنی بدهید.

بعد از نصب:
1. با `https://admin.example.com` وارد شوید. نصاب رمز اولیه و seed مربوط به bootstrap را بعد از ساخت ادمین از `.env` حذف می‌کند؛ آن‌ها را همان موقع در جای امن نگه دارید.
2. **فایل `/opt/melorin/secrets/backup/age-identity.txt` را حتماً جای امن و خارج از سرور کپی کنید.** بدون آن، پشتیبان‌ها قابل بازیابی نیستند.

**SMTP و S3 اختیاری هستند** و بعداً از پنل ادمین (تنظیمات ← یکپارچه‌سازی‌ها) فعال می‌شوند. بدون SMTP فقط ورود با کد ایمیلی کار نمی‌کند. پشتیبان رمزنگاری‌شده هر روز ساعت ۰۲:۰۰ UTC به‌صورت محلی ذخیره می‌شود و اگر S3 فعال باشد روی آن هم کپی می‌شود.

## به‌روزرسانی
**خودکار (پیشنهادی):** با هر push به `main`، workflow به‌نام `deploy.yml` با SSH به سرور وصل می‌شود و `git pull`، build، migration و `up -d` را اجرا می‌کند و نتیجه را در لاگ سرور ثبت می‌کند. راه‌اندازی (یک‌بار):
1. روی سرور کاربری بسازید که مالک `/opt/melorin` و عضو گروه `docker` باشد (`adduser --disabled-password deploy` ، `usermod -aG docker deploy` ، `chown -R deploy:deploy /opt/melorin`).
2. یک جفت کلید SSH مخصوص بسازید، کلید عمومی را به `authorized_keys` همان کاربر اضافه کنید و host key را با `ssh-keyscan -t ed25519 -p 22 IP_سرور` بگیرید.
3. در GitHub (Settings ← Secrets and variables ← Actions) این secretها را بسازید: `DEPLOY_HOST`، `DEPLOY_USER`، `DEPLOY_PORT`، `DEPLOY_SSH_KEY` (کلید خصوصی) و `DEPLOY_KNOWN_HOSTS`. کلید خصوصی فقط همان‌جا بماند.
4. از تب Actions یک‌بار *Deploy ← Run workflow* را اجرا کنید و سبز بودنش را ببینید.

**دستی:** `cd /opt/melorin && git pull --ff-only && docker compose build && docker compose run --rm api alembic upgrade head && docker compose up -d`

## ثبت تغییرات اجباری است
**هر تغییری — کد، تنظیمات یا کار روی سرور — باید ثبت شود**؛ و لازم نیست کسی یادش بماند، چون خودکار ثبت می‌شود. ولی دلیل را خودتان اضافه کنید:

- **کد (در git) ← `docs/CHANGE_LOG.md`:** روی هر push به `main` بات (workflow به‌نام `Changelog`) برای commitهای بدون ورودی ورودی می‌نویسد. در پیام commit بنویسید (`make setup-git` قالبش را فعال می‌کند):
  `Problem:` (مشکل) ، `Action:` (کاری که برای رفعش شد) ، `After:` (نتیجهٔ تأییدشده) ، و در صورت نیاز `Before:` و `Area:`.
- **کار روی سرور ← `var/ops-log.md`:** `scripts/ops_watch.sh` هر ۵ دقیقه تغییر commit، تغییر کلیدهای `.env` (فقط نام، نه مقدار)، دستکاری فایل‌ها و ری‌استارت کانتینرها را خودکار ثبت می‌کند؛ نتیجهٔ deploy هم ثبت می‌شود. دلیل را با `scripts/ops_log.sh` اضافه کنید.

هر ورودی شامل: **قبل**، **مشکل/خطا**، **اقدام برای رفع**، **بعد (نتیجهٔ تأییدشده)**، و چه کسی/چه زمانی. هرگز secret، توکن یا مقدار `.env` را در لاگ ننویسید.
این قانون برای همه است: اعضای تیم، پیمانکاران و دستیارهای هوش مصنوعی. جزئیات: [CONTRIBUTING.md](CONTRIBUTING.md).

### نصب پشت Reverse Proxy موجود

اگر پورت‌های ۸۰ یا ۴۴۳ قبلاً اشغال هستند، نصب را با `EXTERNAL_PROXY=true` اجرا کنید. در این حالت شاپ روی `127.0.0.1:18080`، ادمین روی `127.0.0.1:18081` و API روی `127.0.0.1:18000` قرار می‌گیرد؛ مسیرهای `/api/*` و `/health/*` را به API بدهید. فایل `.env` ابتدا به‌صورت موقت ساخته و فقط پس از موفقیت اعتبارسنجی به‌صورت اتمی منتشر می‌شود.
