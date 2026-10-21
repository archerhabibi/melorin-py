# Melorin ADR / open decisions

## Decided in V1
- Modular monolith; only Core owns PostgreSQL and business rules.
- PostgreSQL ledger is append-only source of truth; balance is a locked projection.
- Internal transactional outbox, polling worker in V1; broker remains replaceable.
- Sanaei and PasarGuard adapters implement one standard interface.
- Manual card receipt flow ships; online gateway adapter is optional and disabled until configured.
- Admin can manually review/retry/attach/refund; provisioning failure never auto-refunds.
- Iranian Rial is default currency, amounts are integers in smallest canonical unit.

## Must be approved before production
- Exact email authentication provider/SMTP and Google OAuth production settings.
- Final debt-limit boundary, reseller wallet funding/adjustment policy, commission debt policy.
- Referral attribution scope (platform vs store).
- JWT/session policy, Celery/ARQ choice, Caddy/Nginx, Sentry and metrics stack.
- S3-compatible storage, RPO/RTO, backup target and restore-test schedule.
- Telegram Event Center group/topic permissions and bot token ownership.
- Admin account bootstrap and mandatory/optional 2FA policy.

Open decisions are runtime-configurable where safe, but are not silently treated as requirements.

## v1.1 decisions applied (2026-10-09)

_Merged from the former 12-Change-Log-v1.1.md._

تاریخ: 2026-10-09

این نسخه بر اساس پاسخ‌های مالک محصول به سؤالات باز به‌روزرسانی شده است.

### تصمیم‌های اعمال‌شده
- ارز قابل تنظیم به تفکیک Store.
- Reseller باید از قبل عضو/مشتری Main Store باشد.
- مشتری هر Reseller فقط Wallet همان Store را شارژ می‌کند و مقصد پرداخت متعلق به همان Store است.
- تمام خریدها فقط از Wallet همان Store پرداخت می‌شوند؛ پرداخت خارجی فقط شارژ Wallet است.
- Reseller مجاز به شارژ Wallet مشتریان خودش است.
- کمیسیون/پاداش قابل انتخاب برای هر طرح؛ انتساب بر اساس اولین معرف ثبت‌شده.
- اتصال خودکار هویت‌ها در صورت تطبیق ایمیل تأییدشده؛ تعارض‌ها برای بازبینی دستی گزارش می‌شوند.
- تغییر مالک VPN Account توسط Admin غیرمجاز.
- ARQ + Redis برای کارهای پس‌زمینه.
- RPO <= 24 ساعت و RTO <= 8 ساعت.
- Reseller API و Outgoing Webhook در V1 پیاده‌سازی می‌شوند.
- Coupon V1 با محدوده Store/دامنه مجاز، creator roles، محدودیت مصرف، بازه اعتبار، سقف تخفیف، عدم ترکیب پیش‌فرض و اعتبارسنجی مرکزی Core.
- Debt limit با شرط توقف `balance <= -debt_limit`.

### موارد باز باقی‌مانده
در سند `10-Roadmap-Open-Decisions.md` ثبت شده‌اند؛ از جمله درگاه پرداخت، Email Auth، روش تمدید، Reverse Proxy، Storage، Session/JWT، Monitoring stack، بازیافت کمیسیون خرج‌شده، تنظیم گروه‌های تلگرام و سیاست‌های تکمیلی ارز و شارژ دستی.
