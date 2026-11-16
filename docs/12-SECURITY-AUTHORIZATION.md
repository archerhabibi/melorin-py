# امنیت و مجوزها / Security & Authorization

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** مدل تهدید، احراز هویت، نقش‌ها و ممیزی.



## English section

**Purpose:** Threat model, authentication, roles and audit.



## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `12-SECURITY-AUTHORIZATION.md`

#### امنیت، هویت و مجوزها
##### اصول
Deny-by-default، least privilege، Core-enforced authorization و جداسازی StoreContext. پنهان‌کردن UI جایگزین Authorization نیست.
##### Authentication
Telegram identity باید معتبرسنجی شود. Website از Google و/یا Email استفاده می‌کند؛ روش دقیق Email باز است. Token/session دارای expiry، refresh/rotation، logout/revoke و محافظت replay باشد. Account linking: پس از تأیید ایمیل، تطبیق ایمیل تأییدشده می‌تواند هویت‌ها را به User مرکزی متصل کند. هر تعارض، چند حساب محتمل یا وضعیت مبهم باید اتصال خودکار را متوقف کرده، رخداد قابل Audit ایجاد و برای بازبینی دستی گزارش شود.
ورود Website با تأیید در ربات تلگرام (Device Authorization با اتصال به مرورگر، تطبیق عدد و نمایش دستگاه/IP) در `docs/08-IDENTITY-ACCOUNT-PERSON.md` توصیف شده است؛ ادمین‌ها از این مسیر وارد نمی‌شوند.
##### Authorization
- Admin: تمام Storeها.
- Reseller: فقط Store، مشتریان، گزارش و عملیات مجاز خودش.
- Customer: داده‌های خودش.
- API credential: scopes محدود و قابلیت disable/revoke.
تست IDOR و cross-store access اجباری.
##### Secrets
Bot token، Panel credential و gateway secrets با encryption-at-rest؛ کلید رمزنگاری جدا از DB. TLS، rotation و masking در log الزامی. Backup رمزنگاری‌شده.
##### Admin
2FA قابل فعال‌سازی و IP restriction اختیاری. Rate limit، anti-brute-force، expiry و ثبت تلاش ناموفق.
##### Audit/Security Events
Append-only audit برای تغییرات مالی، هویت، قیمت، تنظیمات، API credential، refund، provisioning و emergency control. رویدادهای brute force، API abuse، token abuse، linking غیرعادی و تلاش cross-store باید alert شوند. Hash-chain یا export خارج سرور می‌تواند برای tamper evidence قوی‌تر افزوده شود.
##### Coupon و Webhook Security
Coupon scope و quota در Core enforce شوند؛ هرگز به قیمت یا تخفیف ارسالی از Channel اعتماد نشود. Webhook خروجی با HMAC امضا، timestamp و شناسه رویداد یکتا ارسال شود؛ مقصدها allowlist/اعتبارسنجی شوند، SSRF کنترل شود، timeout و retry محدود باشد و secret امضا رمزنگاری‌شده نگهداری و قابل rotation باشد.
##### Privacy
حداقل‌سازی داده شخصی، کنترل دسترسی به Email/Telegram ID/اطلاعات پرداخت، Terms/Privacy versioning و retention. اطلاعات مالی و Audit با حذف عادی User پاک نمی‌شوند.

### منبع / Source: `12-SECURITY-AUTHORIZATION.md`

#### Ops hardening (audit phases P0 / P9)

Status: procedure. Source: `T-AUDIT-2026-11-09` (T17, T20, T21, T25, T28, T32, T33, T47, T48, T53).
Code-side parts of P0 (log redaction T20/T40, 429 handling T22) already live in `core/logging.py` and the bots; this page covers what only an operator can do on the server.

##### 1. Rotate credentials (do first, in this order)

| Credential | Why | How |
|---|---|---|
| GitHub token pasted into a chat (T21) | A token that was shared in text must be treated as leaked | GitHub -> Settings -> Developer settings -> revoke it. Create a **fine-grained** token limited to this repository (Contents + Pull requests: read/write), 30-day expiry |
| Main bot and every reseller bot token (T20) | Old tracebacks in `docker logs` contained the full token URL | BotFather `/revoke`, put the new token in `.env` / the store row, restart only that bot |
| Anything else that appeared in logs or `.env.bak.*` (T33) | Backup copies of `.env` keep old secrets alive | Rotate, then delete the backup file |

After rotating, confirm the logs are clean:

```bash
docker logs --since 24h telegram_main 2>&1 | grep -Eoi 'bot[0-9]{6,}:[A-Za-z0-9_-]{20,}' | head   # must print nothing
```

##### 2. Host hardening script

`scripts/harden_host.sh` is a dry run by default.

```bash
sudo scripts/harden_host.sh                      # shows every change
sudo SSH_PORT=22 NODE_IPS="203.0.113.10" scripts/harden_host.sh --apply
```

It: enables `ufw` (SSH is allowed first; 80/443 open; panel node ports only for `NODE_IPS`), adds a 2 GiB swap file (T25), encrypts or `chmod 600`s plaintext `.sql` dumps (T32) and **lists** (never deletes) untracked files in `/opt/melorin` and extra project copies (T33, T17).
Docker edits iptables itself, so also make sure containers publish `127.0.0.1:PORT` only.

##### 3. Before every cleanup phase

```bash
scripts/phase_snapshot.sh P2 --backup   # annotated tag + encrypted backup
git push origin pre-P2-<timestamp>
```

Test on `/opt/melorin-stage`, never on production first. Roll back by checking out the tag.

##### 4. Repository access

* Give each collaborator **write** access; never share your own token.
* Branch protection on `main`: one approving review, required CI checks (`ruff`, `lint-imports`, `pytest`, `gen_docs --check`), no force-push.

##### 5. Verify (T48, T53)

* Admin panel -> backup settings: confirm `backup_s3` (off-server copy) is enabled.
* Run `scripts/restore_drill_latest.sh` on staging and record the date in `docs/STATUS.md`.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
