# ملورین (Melorin)

پلتفرم چندفروشگاهی فروش VPN. مستندات کامل انگلیسی در [README.md](README.md) است؛ این صفحه فقط نصب و قوانین کار را خلاصه می‌کند.

## نصب روی سرور

**پیش‌نیاز:** سرور اوبونتو با دسترسی root، دو دامنه (فروشگاه و ادمین) که به سرور اشاره کنند، و **آزاد بودن پورت 80 و 443** (گواهی TLS خودکار توسط Caddy گرفته می‌شود).

```bash
curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/scripts/install_server.sh -o install.sh
DOMAIN=shop.example.com ADMIN_DOMAIN=admin.example.com ADMIN_EMAIL=you@example.com bash install.sh
```

نصاب Docker را نصب می‌کند، پروژه را در `/opt/melorin` قرار می‌دهد، **توکن بات اصلی تلگرام** را می‌پرسد (یا `MAIN_BOT_TOKEN=...`)،
همهٔ secretها را خودکار می‌سازد، کلید پشتیبان‌گیری رمزنگاری‌شده را می‌سازد، migration می‌زند و سرویس‌ها را بالا می‌آورد. اجرای دوباره‌اش بی‌خطر است.
بات‌های ریسلر پیش‌فرض خاموش‌اند (`COMPOSE_PROFILES=reseller`). اگر ریپو private است، اسکریپت را دستی به سرور ببرید و `REPO_URL` را با deploy key فقط‌خواندنی بدهید.

بعد از نصب:
1. با `https://admin.example.com` وارد شوید. رمز اولیهٔ ادمین در `/opt/melorin/.env` (کلید `MELORIN_BOOTSTRAP_ADMIN_PASSWORD`) است؛ بعد از اولین ورود عوضش کنید.
2. **فایل `/opt/melorin/secrets/backup/age-identity.txt` را حتماً جای امن و خارج از سرور کپی کنید.** بدون آن، پشتیبان‌ها قابل بازیابی نیستند.

**SMTP و S3 اختیاری هستند** و بعداً از پنل ادمین (تنظیمات ← یکپارچه‌سازی‌ها) فعال می‌شوند. بدون SMTP فقط ورود با کد ایمیلی کار نمی‌کند. پشتیبان رمزنگاری‌شده هر روز ساعت ۰۲:۰۰ UTC به‌صورت محلی ذخیره می‌شود و اگر S3 فعال باشد روی آن هم کپی می‌شود.

به‌روزرسانی: `cd /opt/melorin && git pull --ff-only && docker compose build && docker compose run --rm api alembic upgrade head && docker compose up -d`

## ثبت تغییرات اجباری است
**هر تغییری — کد، تنظیمات یا کار روی سرور — باید در `docs/CHANGE_LOG.md` ثبت شود.** لازم نیست کسی یادش بماند: روی هر push به `main` بات (workflow به‌نام `Changelog`) برای commitهای بدون ورودی خودش ورودی می‌نویسد.
ولی دلیل تغییر را خودتان بدهید؛ در پیام commit این خط‌ها را بنویسید (`make setup-git` قالبش را فعال می‌کند):
`Problem:` (مشکل) ، `Action:` (کاری که برای رفعش شد) ، `After:` (نتیجهٔ تأییدشده) ، و در صورت نیاز `Before:` و `Area:`.

هر ورودی شامل: **قبل**، **مشکل/خطا**، **اقدام برای رفع**، **بعد (نتیجهٔ تأییدشده)**، و چه کسی/چه زمانی. هرگز secret، توکن یا مقدار `.env` را در لاگ ننویسید.
این قانون برای همه است: اعضای تیم، پیمانکاران و دستیارهای هوش مصنوعی. جزئیات: [CONTRIBUTING.md](CONTRIBUTING.md).
