# Install report, run 2 / گزارش نصب، اجرای دوم (2026-11-11)

Host: Ubuntu 22.04, 2 vCPU/4 GB, clean. Domains shop.88promax.ir, admin.88promax.ir. Installed from `main` (no release tag yet).

## English
**Result:** 12/12 containers healthy, both HTTPS endpoints 200 with valid TLS, bot token valid, ufw (22/80/443), fail2ban, 2 GiB swap, credentials file created.

**Problem found:** `alertmanager` crash-looped with `Permission denied` on `/etc/alertmanager/entrypoint.sh` and the whole stack waited on it. Cause: the repo was cloned by hand under `umask 077`, then the installer ran. The existing umask fix only protects fresh clones made by `get.sh`; it does not repair a checkout that already exists. Fix (branch `fix/install-existing-checkout-perms`): `get.sh` and `install_server.sh` re-apply go+r on all files except `.git`, `secrets/`, `.env`. Re-running the installer afterwards brought everything up (it is idempotent).

**What to ask during install (keep five):** store domain, admin domain, admin e-mail, bot token, admin Telegram ID. Nothing more.

**After install (already automated by post_install.sh):** credentials file, swap, ufw, fail2ban, verification.

**Still your decision (not changed, on purpose):**
1. SSH: `PermitRootLogin yes` and password auth are on, `authorized_keys` is empty. Add your key first, then set key-only login; disabling now would lock you out.
2. Copy `/opt/melorin/secrets/backup/age-identity.txt` off the server.
3. Login to admin, add the TOTP seed, change the password, delete `/root/melorin-credentials.txt`; press Start on the bot.
4. Off-site backup (S3/rclone), SMTP, payment methods and VPN panel in Admin.
5. Tag a release (`v0.1.0`) so installs stop tracking moving `main`.
6. Rotate the GitHub PAT and the Telegram bot token: both were pasted in a chat.

## فارسی
**نتیجه:** ۱۲ کانتینر سالم، هر دو آدرس HTTPS با کد ۲۰۰ و TLS معتبر، توکن ربات معتبر، فایروال (22/80/443)، fail2ban، swap دو گیگ و فایل اعتبارنامه ساخته شد.

**مشکل پیدا شده:** کانتینر `alertmanager` مدام با `Permission denied` روی `entrypoint.sh` کرش می‌کرد و بقیه سرویس‌ها منتظر آن ماندند. علت: مخزن دستی با `umask 077` clone شده بود. رفع قبلی `umask` فقط برای clone تازه توسط `get.sh` کار می‌کند و checkout موجود را درست نمی‌کند. رفع (برنچ `fix/install-existing-checkout-perms`): `get.sh` و `install_server.sh` دسترسی خواندن را برای همه فایل‌ها به‌جز `.git`، `secrets/` و `.env` دوباره اعمال می‌کنند. اجرای مجدد نصب‌کننده (idempotent) همه چیز را بالا آورد.

**چه چیزهایی هنگام نصب گرفته شود (همان پنج مورد):** دامنه فروشگاه، دامنه ادمین، ایمیل ادمین، توکن ربات، آیدی عددی ادمین.

**بعد از نصب (خودکار توسط post_install.sh):** فایل اعتبارنامه، swap، ufw، fail2ban، راستی‌آزمایی.

**تصمیم با شما (عمداً تغییر داده نشد):**
۱. SSH: ورود root و رمز عبور فعال است و `authorized_keys` خالی است. اول کلید خود را اضافه کنید، بعد ورود فقط با کلید؛ غیرفعال‌کردن فعلی شما را قفل می‌کند.
۲. فایل `/opt/melorin/secrets/backup/age-identity.txt` را بیرون از سرور نگه دارید.
۳. وارد پنل ادمین شوید، TOTP را اضافه کنید، رمز را عوض کنید، `/root/melorin-credentials.txt` را حذف کنید و در ربات Start بزنید.
۴. بکاپ بیرونی، SMTP، روش پرداخت و پنل VPN را در بخش ادمین تنظیم کنید.
۵. تگ `v0.1.0` بسازید تا نصب‌ها از `main` متحرک استفاده نکنند.
۶. توکن گیت‌هاب و توکن ربات تلگرام را عوض کنید؛ هر دو در چت قرار گرفتند.
