# Glossary / واژه‌نامه

One word, one meaning (audit T49). When a document or a commit says one of these words, it means exactly the following.
هر واژه فقط یک معنی دارد؛ در اسناد و commitها همین معنی مراد است.

| Term | Meaning | معنی |
|---|---|---|
| **Core** (capital C) | The whole backend product: the API process **plus** the worker process, i.e. everything under `apps/api/melorin`. | کل بک‌اند: فرایند API و فرایند worker (همهٔ `apps/api/melorin`). |
| **`melorin.core`** / "core package" | Only the infrastructure package `apps/api/melorin/core` (config, db, crypto, channel plumbing, logging). Never a business rule. Always written in code font. | فقط پکیج زیرساخت؛ هیچ قاعدهٔ کسب‌وکاری ندارد. همیشه با فونت کد نوشته می‌شود. |
| **`domain`** | Pure business rules (pricing, ledger math, coupons). Imports nothing from the rest of Melorin (enforced by import-linter). | قواعد خالص کسب‌وکار؛ هیچ چیز از بیرون import نمی‌کند. |
| **module** | A bounded context under `melorin/modules/<name>` (vpn, orders, payments, panelops, ...). | یک بخش مستقل زیر `modules/`. |
| **channel** | A protocol adapter (Telegram, web login). Translates a protocol; owns no business rule. | آداپتور پروتکل (تلگرام، ورود وب). |
| **adapter** | A driver for one panel family under `modules/panel_integrations/adapters` (pasarguard, sanaei, upstream_bot). | درایور یک خانوادهٔ پنل. |
| **panel** | An external VPN panel (e.g. PasarGuard). It owns volume, expiry and status; Melorin only mediates. | پنل VPN بیرونی؛ مالک حجم/انقضا/وضعیت است. |
| **mediator rule** | Melorin never stores panel-owned numbers; it reads them live (`vpn.PanelReader`) and caches them only within the single freshness policy. | ملورین داده‌های پنل را ذخیره نمی‌کند، زنده می‌خواند. |
| **outbox** | The `outbox_events` table: events written in the same transaction as the change, delivered by the worker. | رخدادهای هم‌تراکنش با تغییر، که worker ارسال می‌کند. |
| **job** | One arq task in `worker/jobs.py`, always wrapped by `tracked_job`. Cron jobs are listed in `worker/arq_app.py`. | یک کار arq با wrapper یکسان. |
| **bot** | A Telegram bot process under `apps/telegram-*` (customer bot, reseller bot). It holds no business rule and talks to Core over HTTP. | فرایند ربات تلگرام؛ فقط با Core از راه HTTP حرف می‌زند. |
| **store** | A tenant (main store or reseller store); wallets, currency and payment targets are store-scoped. | مستأجر (فروشگاه اصلی یا نماینده). |
| **retention** | Deleting *finished* operational rows after a window (`worker/retention.py`); never ledger, orders or audit log. | حذف ردیف‌های تمام‌شده پس از یک بازه؛ هرگز ledger/سفارش/audit. |
