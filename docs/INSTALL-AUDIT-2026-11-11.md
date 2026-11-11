# Install audit / گزارش ممیزی نصب (2026-11-11)

Server: Ubuntu 22.04, 2 vCPU, 4 GB RAM, Hetzner. Domains: shop.88promax.ir, admin.88promax.ir. One-liner from the README, followed by the menu's unattended install path.

## English

### 1. Errors found while installing (fixed on `fix/install-hardening`)
| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | `alertmanager` crash-looped (`can't open /etc/alertmanager/entrypoint.sh: Permission denied`); the whole stack stayed down because Prometheus, API-dependent services and Caddy wait on it | The host shell had `umask 077`, so `git clone` produced 0600/0700 files. Containers that run as `nobody` (alertmanager, prometheus) cannot read bind-mounted config | `umask 022` at the top of `get.sh` and `scripts/install_server.sh` (secrets are chmod-ed explicitly anyway) |
| 2 | `melorin-caddy` stayed `unhealthy` although both sites worked | Healthcheck `wget http://127.0.0.1/health/live` was caught by the catch-all `http://` redirect and sent to `https://127.0.0.1` (no certificate) | Loopback-only exception in `infra/Caddyfile` that proxies `/health/live` to the API; everything else still redirects |

The installer is idempotent: after the fix, re-running it finished cleanly. Result: 12/12 containers healthy, both domains return HTTP 200 with valid TLS, bot token verified.

### 2. What to collect during install, what to do after (branch `feat/post-install-hardening`)
Already collected today (5 inputs): store domain, admin domain, admin e-mail, bot token, admin Telegram ID. Keep it at five; more questions hurt the one-line experience.

Suggested improvements, implemented in `scripts/post_install.sh` (runs at the end of the installer, never fatal, opt-out `POST_INSTALL=0`, re-runnable):
1. **Credentials file** `/root/melorin-credentials.txt` (mode 600): the one-time password is removed from `.env` after bootstrap, so a scrolled terminal loses it. Delete after first login.
2. **Swap 2 GiB**: container caps add up to 3.5 GiB on a 4 GB host; swap turns an OOM kill into a slow moment.
3. **Firewall (ufw)**: SSH port is detected and allowed first, then 80/443.
4. **fail2ban** (default sshd jail).
5. **Verification report**: both HTTPS endpoints, Telegram token (`getMe`), container health, and a reminder to copy the backup age key off the server.
6. `secrets/metrics-token` kept out of `git status` (updates and drift checks stay quiet).

Suggested next, not done automatically (needs your decision): SSH key-only login and `PermitRootLogin prohibit-password`; off-site backup target (S3/rclone) in Admin; SMTP for e-mail login codes; first payment method, VPN panel (Sanaei/PasarGuard) and Zarinpal in Admin after install; Google/OIDC login if wanted; a release tag `v0.1.0` so installs stop tracking moving `main` (get.sh already warns about it); unattended-upgrades is already active on this host.

### 3. After install (today's server)
Open https://admin.88promax.ir, log in with archerhabibi@gmail.com and the one-time password from `/root/melorin-credentials.txt`, add the TOTP seed to an authenticator, change the password, delete the file. Open the bot once and press Start so admin alerts reach Telegram ID 1992426945. Copy `/opt/melorin/secrets/backup/age-identity.txt` off the server.

## فارسی

### ۱. خطاهای نصب و رفع آن‌ها (برنچ `fix/install-hardening`)
| # | علامت | علت ریشه‌ای | رفع |
|---|---|---|---|
| ۱ | کانتینر `alertmanager` مدام کرش می‌کرد (`Permission denied` روی entrypoint.sh) و کل سرویس‌ها بالا نمی‌آمدند، چون Prometheus، API و Caddy منتظر آن هستند | شل سرور `umask 077` داشت و فایل‌های clone با دسترسی 0600/0700 ساخته شدند؛ کانتینرهایی که با کاربر `nobody` اجرا می‌شوند (alertmanager و prometheus) نمی‌توانند فایل‌های mount شده را بخوانند | افزودن `umask 022` به ابتدای `get.sh` و `scripts/install_server.sh` (فایل‌های حساس به‌صورت جداگانه chmod می‌شوند) |
| ۲ | کانتینر caddy با وجود کار کردن سایت‌ها «unhealthy» می‌ماند | healthcheck یعنی `wget http://127.0.0.1/health/live` توسط ریدایرکت عمومی `http://` به `https://127.0.0.1` هدایت می‌شد که گواهی ندارد | استثنای فقط-loopback در `infra/Caddyfile` که `/health/live` را به API می‌فرستد؛ بقیه مسیرها همچنان ریدایرکت می‌شوند |

نصب‌کننده idempotent است؛ بعد از رفع، اجرای مجدد تمیز تمام شد. نتیجه: ۱۲ کانتینر سالم، هر دو دامنه با HTTP 200 و TLS معتبر، توکن ربات تأیید شد.

### ۲. چه چیزهایی هنگام نصب گرفته شود و بعد از نصب چه شود (برنچ `feat/post-install-hardening`)
اکنون پنج ورودی گرفته می‌شود: دامنه فروشگاه، دامنه ادمین، ایمیل ادمین، توکن ربات، آیدی عددی تلگرام ادمین. به نظرم همین پنج تا بماند تا تجربه تک‌خطی خراب نشود.

بهبودهای پیاده‌سازی‌شده در `scripts/post_install.sh` (انتهای نصب اجرا می‌شود، هرگز نصب را خراب نمی‌کند، با `POST_INSTALL=0` غیرفعال می‌شود و قابل اجرای مجدد است):
۱. **فایل اعتبارنامه** `/root/melorin-credentials.txt` با دسترسی 600: رمز یک‌بارمصرف بعد از bootstrap از `.env` حذف می‌شود و اگر ترمینال اسکرول شود از دست می‌رود. بعد از اولین ورود حذفش کنید.
۲. **Swap دو گیگابایتی**: سقف حافظه کانتینرها روی سرور ۴ گیگ حدود ۳٫۵ گیگ است.
۳. **فایروال ufw**: پورت SSH شناسایی و اول باز می‌شود، سپس 80 و 443.
۴. **fail2ban** با jail پیش‌فرض sshd.
۵. **گزارش راستی‌آزمایی**: هر دو آدرس HTTPS، توکن تلگرام، سلامت کانتینرها و یادآوری انتقال کلید بکاپ به بیرون از سرور.
۶. فایل `secrets/metrics-token` از `git status` کنار گذاشته می‌شود.

پیشنهادهای بعدی که تصمیمش با شماست: ورود SSH فقط با کلید و `PermitRootLogin prohibit-password`؛ مقصد بکاپ بیرونی (S3/rclone)؛ SMTP برای کد ایمیلی ورود؛ افزودن پنل VPN (سنایی/پاسارگارد)، روش پرداخت و زرین‌پال در پنل ادمین؛ ورود گوگل/OIDC در صورت نیاز؛ ساخت تگ `v0.1.0` تا نصب‌ها از `main` متحرک استفاده نکنند.

### ۳. بعد از نصب (همین سرور)
وارد https://admin.88promax.ir شوید، با archerhabibi@gmail.com و رمز موجود در `/root/melorin-credentials.txt` لاگین کنید، seed کد TOTP را در برنامه احراز هویت اضافه کنید، رمز را عوض و فایل را حذف کنید. یک بار ربات را باز و Start بزنید تا هشدارها به آیدی 1992426945 برسد. فایل `/opt/melorin/secrets/backup/age-identity.txt` را حتماً بیرون از سرور نگه دارید.
