# نقشه راه و بدهی فنی / Roadmap & Technical Debt

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** نقشه راه، بدهی فنی و ثبت یافته‌های ممیزی. وضعیت کد فعلی بر گزارش قدیمی اولویت دارد. وضعیتها: `Confirmed`، `Fixed`، `Superseded`، `Not Reproducible`، `Open`.

**رجیستری یافته‌ها (مطابق TODO و گزارش r22/r23)**
- `Fixed`: محافظ gen_docs --check؛ گروه‌بندی منوی سیستم/امنیت؛ سرویس یک‌بارمصرف `migrate` در compose؛ mypy روی کل `melorin`؛ bandit B104؛ فایل‌های بزرگ admin-web (هیچ فایلی بیش از ۴۵۰ خط نیست)؛ نبود specهای Playwright اسکیپ‌شده؛ UI اتصال حساب‌ها، دکمهٔ ربات، تست‌های مالی و reauth.
- `Superseded`: حذف consolidation؛ تأیید دستی همهٔ انتقال‌ها؛ `product_codes` (سند 06).
- `Fixed` (این نوبت): اثبات مالکیت قوی‌تر برای حساب‌های فقط-Google/تلگرام (توکن Google یا کد ربات)؛ `authFetch` فقط در `api/api.ts` باقی است و دانلود فایل از `downloadFile` می‌گذرد؛ ارسال اعلان به تلگرام لغوشده؛ مجوز دکمه‌های تلگرام (فقط owner) تثبیت شد.
- `Open`: فقط شواهد محیط واقعی (فهرست `Not verifiable here` پایین).
- `Not verifiable here`: پنل واقعی PasarGuard/Sanaei، ربات واقعی تلگرام، زرین‌پال، Caddy + Prometheus، تمرین restore از S3.

**گزارش اعتبارسنجی آخر:** مجموعهٔ تست API بدون خطا، baseline روی دیتابیس خالی بدون drift، lint/mypy/import-linter تمیز (جزئیات در سند 20).

**نقشه راه:** ۰ تثبیت نیازمندی‌ها؛ ۱ Foundation؛ ۲ Catalog/Wallet/پرداخت؛ ۳ سفارش و پنل‌ها؛ ۴ ادمین، وب، ربات‌ها؛ ۵ Referral/Ticket/Reseller API؛ ۶ production hardening و E2E. همهٔ مراحل نماینده و ساخت تا سطح کد انجام شده‌اند؛ آنچه باقی است شواهد اجرای واقعی (staging) و release است.

## English section

**Purpose:** roadmap, technical debt and the audit-findings register. Current code beats an old report. Statuses: `Confirmed`, `Fixed`, `Superseded`, `Not Reproducible`, `Open`.

**Findings register (from TODO and the r22/r23 reports)**
- `Fixed`: gen_docs --check guard; system/security menu grouping; one-shot `migrate` service in compose; mypy over all of `melorin`; bandit B104; large admin-web files (none is above 450 lines now); no skipped Playwright specs; account-linking site UI, bot menu button, financial tests and reauth.
- `Superseded`: removal of consolidation; manual approval of every transfer; `product_codes` (doc 06).
- `Fixed` (this round): a stronger ownership proof for Google/Telegram-only accounts (Google token or bot code); `authFetch` now lives only in `api/api.ts` and file downloads go through `downloadFile`; notifications to a revoked Telegram; the Telegram-buttons permission (owner only) is settled.
- `Open`: only real-environment evidence (the `Not verifiable here` list below).
- `Not verifiable here`: real PasarGuard/Sanaei panels, real Telegram bots, Zarinpal, Caddy + Prometheus profile, the S3 restore drill.

**Latest verification:** the API suite is green, the baseline on an empty database has no drift, and lint/mypy/import-linter are clean (details in doc 20).

**Roadmap:** 0 requirements; 1 Foundation; 2 Catalog/Wallet/payments; 3 orders and panels; 4 admin, web and bots; 5 referral/ticket/reseller API; 6 production hardening and E2E. All phases are implemented in code; what remains is real-environment (staging) evidence and the release decision.

## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `21-ROADMAP-TECHNICAL-DEBT.md`

#### نقشه راه و تصمیم‌های باز
##### فازها
0. تثبیت نیازمندی، ADRها، State Machineها و مدل Money/Ledger.
1. Foundation: repo/CI، Core، DB، Redis، Identity، StoreContext، Authorization، Audit.
2. Catalog/Pricing، Wallet/Ledger، Payment abstraction و کارت‌به‌کارت.
3. Order State Machine، Server/Panel registry، Sanaei/PasarGuard adapters، retry/manual review/reconciliation.
4. Admin Panel، Website/Guest Checkout، Main Bot، Reseller Store/Bot و linking.
5. Referral، Test Account، Ticket، notification topics، Reseller API و گزارش‌ها.
6. Production hardening، monitoring، backup/restore، security review و E2E.
##### تصمیم‌های قطعی مالک محصول (ثبت‌شده در نسخه 1.1)
1. واحد پول برای هر Store قابل تنظیم است؛ Currency باید صریح در تمام اسناد مالی ذخیره شود.
2. Reseller متقاضی باید پیش از درخواست/فعال‌سازی، عضو و مشتری Main Store باشد.
3. مشتری Reseller، Wallet خود را در Store همان Reseller شارژ می‌کند؛ مقصد پرداخت باید متعلق به همان Store باشد.
4. تمام خریدها فقط با Wallet همان Store انجام می‌شوند؛ درگاه/پرداخت دستی فقط Wallet را شارژ می‌کند.
5. Reseller مجاز است Wallet مشتریان خودش را شارژ کند.
6. مدل کمیسیون/پاداش توسط Admin برای هر طرح قابل انتخاب است؛ انتساب معرف بر اساس اولین معرف ثبت‌شده است.
7. ایمیل تأییدشده منطبق می‌تواند برای اتصال خودکار هویت‌ها استفاده شود؛ موارد تکراری/متعارض باید برای بازبینی دستی گزارش شوند.
8. تغییر مالک VPN Account توسط Admin در V1 غیرمجاز است.
9. صف کارهای پس‌زمینه: ARQ + Redis.
10. RPO حداکثر 24 ساعت؛ RTO حداکثر 8 ساعت.
11. Reseller API در V1 پیاده‌سازی و فعال است.
12. Outgoing Webhook در V1 پیاده‌سازی می‌شود.
13. Coupon در V1: سازنده Admin یا Reseller مجاز؛ Store scope یا دامنه صریحاً مجازشده توسط Admin؛ Reseller فقط Store خودش؛ ترکیب به‌صورت پیش‌فرض ممنوع؛ Core یک Coupon معتبر را اعمال می‌کند؛ سقف تخفیف، اعتبار زمانی و سقف مصرف کلی/هر مشتری قابل تنظیم؛ اعتبارسنجی فقط در Core.
14. Debt limit به‌صورت مقدار مثبت ذخیره و خرید در `balance <= -debt_limit` متوقف می‌شود.

##### تصمیم‌های باز باقی‌مانده
1. درگاه آنلاین V1 و روش دقیق تأیید کارت‌به‌کارت/پرداخت دستی.
2. روش ورود ایمیلی و سیاست یکتایی Email در سطح Platform.
3. مدل دقیق تمدید سرویس: بسته‌های ثابت یا مقادیر آزاد؛ اصل فعلی افزایش زمان و حجم حفظ می‌شود.
4. Nginx یا Caddy.
5. Local یا S3-compatible برای فایل‌ها.
6. JWT/Refresh Token یا Session سمت سرور.
7. Stack نهایی Monitoring، Logging و Error Tracking.
8. سیاست دقیق بازیافت کمیسیون در صورتی که کمیسیون قبلاً خرج شده باشد؛ پیشنهاد فعلی کسر از کمیسیون‌های آینده است.
9. چه کسی مقصد گروه/Topic تلگرام را پیکربندی کند و جریان تأیید آن.
10. قواعد نهایی برخورد با چند User دارای ایمیل تأییدشده یکسان و فرآیند بررسی دستی.
11. آیا پاداش معرفی اولیه جدا از کمیسیون خریدهای بعدی فعال است و مدل آن برای هر طرح چگونه انتخاب می‌شود.
12. سیاست دقیق شارژ دستی Wallet مشتری توسط Reseller (چه نقش‌هایی مجازند و چه نوع سند/تأییدی لازم است)؛ مجاز بودن قابلیت قطعی است.
13. نحوه نمایش نرخ تبدیل و عملیات میان Storeهایی که Currency متفاوت دارند؛ تبدیل خودکار بین ارزها ممنوع تا سیاست مشخص شود.

##### اصل تصمیم
پاسخ کسب‌وکاری مالک محصول بر جزئیات فنی اولویت دارد. برای تصمیم فنی باز، ساده‌ترین گزینه امن V1 انتخاب و در ADR ثبت شود. Future-ready بودن به معنی پیاده‌سازی همه قابلیت‌ها در V1 نیست.

### منبع / Source: `21-ROADMAP-TECHNICAL-DEBT.md`

> **Historical report.** Superseded by `docs/21-ROADMAP-TECHNICAL-DEBT.md` (status of every finding and the open debt register).

#### گزارش ممیزی کل پروژه Melorin

**تاریخ:** ۱۵ نوامبر ۲۰۲۶  
**شاخه:** `feat/arch-admin-ui-r11-typed-payments`  
**محیط اجرا:** Ubuntu 24.04، Python 3.12.3، Node 22، Docker 29، PostgreSQL 16 و Redis 7

##### ۱. خلاصه

هیچ خطای مسدودکننده یا آسیب‌پذیری امنیتی بحرانی پیدا نشد. مسیر پول (کیف پول، سفارش، provisioning)، migration از DB خالی و Compose کامل با اجرای واقعی پاس شدند. ایرادهای باقی‌مانده از جنس بدهی فنی، کارهای نیمه‌تمام و مواردی هستند که بدون محیط واقعی قابل تأیید نیستند.

##### ۲. نتایج اجراشده

| کنترل | نتیجه |
|---|---|
| تست API (pytest) | ۲۷۲۰ پاس، ۱۱ skip |
| تست پنل ادمین (vitest) | ۳۰۱ پاس در ۳۹ فایل |
| تست فروشگاه (vitest) | ۷۹ پاس در ۱۴ فایل |
| lint-imports | ۸ از ۸ قرارداد سالم |
| ruff (check و format) | تمیز |
| mypy با تنظیم خود پروژه | بدون خطا در ۱۰۸ فایل |
| eslint، tsc، prettier، build هر دو وب‌اپ | تمیز |
| گاردهای منبعی (G001-G010، frontend contracts، quality config، ops P0) | پاس |
| `gen_docs --check` و `gen_api_client --check` و `verify_runtime` | پاس (پس از اصلاح ایراد ۱) |
| Migration از DB خالی تا head | پاس |
| `docker compose up --build` | همه سرویس‌ها healthy |
| `scripts/e2e_smoke.py` روی استک واقعی | همه پاس |
| Playwright (store + admin) | ۲۶ پاس، ۲ skip |
| `pip-audit` و `npm audit` (prod) | بدون آسیب‌پذیری شناخته‌شده (web-kit نامشخص، ایراد ۵) |
| اسکن راز در کد (`git grep`) | موردی پیدا نشد |
| bandit (سطح متوسط و بالا) | ۱ مورد (ایراد ۹) |

##### ۳. ایرادها

###### اصلاح‌شده در همین نوبت

| # | شدت | ایراد | اصلاح |
|---|---|---|---|
| ۱ | متوسط | `gen_docs.py --check` (گارد CI مستندات) شکست می‌خورد: `docs/06-ARCHITECTURE-DECISIONS.md` نام head ماگریشن را به صورت ثابت نوشته بود | متن به «مرجع: docs/STATUS.md» تغییر کرد |
| ۲ | کم | `SettingsView` هم static و هم lazy import شده بود (هشدار Vite) و code-split بی‌اثر بود | `ChangeAdminPassword` به فایل جدا رفت |
| ۳ | کم | نام گروه منوهای «سیستم» مفهوم امنیت را نمی‌رساند، و IP allowlist کنار SMTP/Backup بود | گروه «سیستم و امنیت» و تب جدای امنیت دسترسی ادمین |

###### بازمانده (با اولویت)

| # | شدت | ایراد | شواهد | پیشنهاد |
|---|---|---|---|---|
| ۴ | متوسط | `docker compose up` بدون migration قبلی خطای `relation "stores" does not exist` می‌دهد (مثلاً در لاگ بات‌ها). فقط `melorin.sh` اول migrate می‌کند | اجرای زنده | یک سرویس one-shot `migrate` که api و worker به او وابسته باشند، یا دستور migrate در README به شکل الزامی |
| ۵ | متوسط | `packages/web-kit` فایل lock ندارد؛ `npm audit` روی آن اجرا نمی‌شود و نصب‌ها قابل تکرار نیستند | `npm i --package-lock-only` و افزودن به CI |
| ۶ | متوسط | هنوز ۷۸ استفاده از `authFetch` در ۳۵ فایل پنل ادمین (فاز ۳ گزارش ممیزی معماری نیمه‌کاره). شامل Settings، products، bundles، tickets، reports، همه Store tabs | `grep -rn authFetch apps/admin-web/src` | مهاجرت تدریجی به `typedClient` (همان‌گونه که r6 تا r12 انجام شد)، اول Settings و Products |
| ۷ | کم | mypy فقط روی `core`، `worker`، `domain`، `kernel`، `wallet`، `catalog` اجرا می‌شود. اجرای بدون محدودیت ۳۷۰ خطا در ۶۹ فایل نشان می‌دهد (مثل `orders/provisioning.py`: خطاهای `Server \| None` و `Panel \| None`) | اجرای دستی mypy | گسترش `files` به یک پکیج در هر بار، اول `orders` و `identity` و `reseller` (خود پروژه همین را نوشته) |
| ۸ | کم | ۲ مورد کد مرده توسط vulture: متغیر `initiator` در `kernel/models/vpn.py:242` و import بی‌استفاده `CursorResult` در `worker/jobs_identity.py:9` | اجرای `vulture` | حذف بعد از بررسی اینکه متغیر به یک قرارداد مربوط نیست |
| ۹ | کم | bandit B104: bind به همه اینترفیس‌ها در `melorin/__main__.py` | اجرای `bandit` | محتملاً عمدی برای کانتینر؛ با `# nosec B104` و توضیح نشان بده (در Compose فقط شبکه داخلی است) |
| ۱۰ | کم | shellcheck: `melorin.sh` خط ۲۳۸ و ۲۳۹ (SC2097/SC2098) متغیرهای `APP_DIR` و مشابه در همان خط مقداردهی و خوانده می‌شوند؛ `scripts/ops_watch.sh:9` متغیر `APP` استفاده نمی‌شود | اجرای `shellcheck -S warning` | مقداردهی قبل از فراخوانی، حذف `APP` |
| ۱۱ | کم | فایل‌های پنل بزرگ: `PanelAdminsView` (۸۳۳ خط)، `kit.tsx` (۷۸۲)، `UpstreamBotFields` (۷۲۱)، `TicketConversation` (۶۹۸)، `ReportsView` (۶۸۷) | `wc -l` | همان رویکرد گزارش معماری: جابجایی خالص، نه بازنویسی |
| ۱۲ | کم | ۲ اسپک Playwright (پرداخت کارت‌به‌کارت توسط ادمین و خرید مشتری) همیشه skip هستند چون staging سیدشده لازم دارند | خروجی Playwright | با `bootstrap` + `MELORIN_ALLOW_MOCK_PROVIDERS=true` وصل شوند (همان کاری که smoke می‌کند) |

###### تصمیم محصولی باز

| # | موضوع | توضیح |
|---|---|---|
| ۱۳ | مجوز «عملیات گروهی روی پنل» | فعلاً فقط ناحیه `infrastructure`. اگر پشتیبانی هم باید بتواند انجام دهد، مدل مجوز باید بازطراحی شود (گزارش ممیزی معماری، بخش ۵.۴) |
| ۱۴ | ناحیه مجوز «دکمه‌های تلگرام» | در گروه «ارتباطات» است ولی ناحیه مجوزش `system` است. اگر عمدی است باید در ماتریس دسترسی نوشته شود |

###### موارد بدون محیط واقعی قابل تأیید نیستند

- ربات‌های تلگرام با توکن واقعی
- درگاههای پرداخت (Zarinpal و غیره)
- پنل PasarGuard واقعی (همه تست‌ها با mock provider انجام شده‌اند)
- Caddy و TLS با دامنه واقعی، و بازیابی backup از S3
- بار و کارایی تحت ترافیک واقعی

##### ۴. نکته امنیتی عملیاتی

توکن GitHub به صورت متن ساده در چت ارسال شده است؛ آن را revoke کنید. روی سرور آزمایشی هم `.env` با مقادیر تستی (رمز ادمین و TOTP نمونه) ساخته شد؛ این مقادیر نباید به هیچ محیط جدی منتقل شوند.

### منبع / Source: `21-ROADMAP-TECHNICAL-DEBT.md`

#### Melorin: architecture audit status (r18)

**Branch:** `refactor/audit-r18-impl` (on top of r17, merge commit `4aa0cdd`)
**Replaces as the live reference:** `docs/21-ROADMAP-TECHNICAL-DEBT.md` (kept as a historical report; its findings are mapped to decisions in the table below).

##### 1. What r18 changed

| Area | Change |
|---|---|
| Admin menu | «تیکت‌ها» moved from «فروش و عملیات» to the renamed group «اعلان‌ها، ارتباطات و پشتیبانی» (broadcast, event center, tickets). UI grouping only: tickets, notifications and the event center remain separate backend modules. Still 8 groups. |
| Menu tests | `nav-structure.test.js` pins the group, `nav-role-matrix.test.js` pins what owner / manager / finance / support / viewer see. |
| Payments | `payments/bank_sms.py` (654 lines) is now the package `payments/bank_sms/` (`config`, `authentication`, `matching`, `reconciliation`, `ingestion`, `review`). Every old name is still importable from `melorin.modules.payments.bank_sms`. No behaviour change. |
| Loyalty | `loyalty/service.py` (777 lines) is split into `common`, `tiers`, `program`, `rewards`, `ledger`, `earning`, `redemption`, `adjustments`, `summary`. `service.py` stays the facade the worker and tests patch. |
| Referral | `referral/service.py` (480) split into `attach`, `commissions`, `rules`; facade kept. |
| Reports | `reports/analytics.py` (509) split into `analytics_compute` (pure computation), `analytics_queries` (DB reads) and the facade (`build_analytics`, CSV). |
| Dead code | 14 unreferenced backend functions / schemas and 3 unreferenced admin-web exports removed (list in the commit). Vulture at 80% confidence reports nothing. |
| Admin web layout | `apps/admin-web/src` is now `app/` (shell, nav, routes, access), `api/` and `features/<feature>/`. Pure moves; `kit*`, `ui`, `dataKit`, `charts`, `theme` stay at the root until a `shared/` pass. Python contract helpers resolve moved files by name (`_source.web_file`). |

##### 2. Old audit findings (AUDIT-2026-11-15) and their status

| Finding | Status |
|---|---|
| web-kit lockfile missing | fixed (r13+) |
| 78 `authFetch` uses | typed client migration done; 2 CSV downloads stay on purpose (raw response) |
| mypy scope | whole backend gated |
| legacy router re-exports | removed |
| Telegram buttons group vs `system` permission | kept in «سیستم و امنیت» on purpose (owner only) |
| large Frontend files | feature layout done; the files themselves are still large (see register) |

##### 3. Technical debt register (open items only)

| # | Item | Why it stays open |
|---|---|---|
| 1 | `upstream_bot/adapter.py` (543 lines after r19) | r19 moved the defaults (`config.py`) and the mapping store / chat lock (`state.py`) out. The purchase, renewal and refund flows stay in one class on purpose: they are an ordered, stateful bot protocol. |
| 2 | (r19: AdminTeamView 620 to 156, ResellersView 643 to 203, OrdersView 533 to 328 via AdminTeamParts, ResellerParts, OrderParts, OrderDrawer) Remaining large admin-web files (`ResellersView`, `PanelsView`, `AdminTeamView`, `UpstreamBotFields`, `TelegramLoginSettings`, `ServerForm`, `infra`, `OrdersView`, `ReportsView`, 530 to 640 lines each) | Moved into feature folders; splitting their bodies is a behaviour-risk change and needs its own pure-move PRs. |
| 3 | ~~`shared/` folder in admin-web~~ | done in r19: `kit*`, `ui`, `dataKit`, `charts`, `palette`, `theme`, `Trend`, `types`, `useDialog` now live in `src/shared/`. |
| 4 | Evidence that needs real systems | real PasarGuard panel, real Telegram bots, Zarinpal, Caddy + Prometheus/Alertmanager profile, Playwright, backup restore drill, upgrade from an older database |
| 5 | Rotate the GitHub token that was pasted into chat | security hygiene, outside the repository |

##### 4. Target architecture (unchanged principle)

Modular monolith. Business logic only in `domain`, `kernel` and the owning module; admin web, store web and bots only consume the API. Payments/Wallet, Orders/VPN accounts, PanelOps/Panel integrations, Identity/Reseller, Notifications/Event center/Broadcast, Referral/Loyalty stay separate modules. File splits keep a facade module so callers, workers and test patch points do not move.

##### 5. Verification run for r18 (2026-11-15, Ubuntu 24.04, Python 3.12, Node 22)

| Control | Result |
|---|---|
| import-linter | 8 of 8 contracts kept |
| ruff check / format | clean |
| mypy | clean, 369 source files |
| API suite (not integration, not concurrency) | 2730 passed, 11 skipped (two tests were adjusted for the splits: a source-reading contract and one monkeypatch target) |
| admin-web | tsc, eslint, vitest 42 files / 309 tests passed |
| PostgreSQL 16 lane (`TEST_PG_URL`) | 8 passed |
| integration + concurrency markers on PostgreSQL 16 + Redis 7 | 11 passed, 1 skipped |
| alembic upgrade head from an empty database, alembic check | reached head, no drift |
| repo guards (`gen_docs --check`, G001-G010, frontend contracts, quality config, ops P0) | passed |

Not run: real panels, Telegram bots, Zarinpal, Caddy/Prometheus profile, Playwright, backup restore drill, upgrade from an older database.

### منبع / Source: `TODO.md`

##### TODO: audit + account-linking checklist

Source: docs/21-ROADMAP-TECHNICAL-DEBT.md and docs/07-DOMAIN-DATA-MODEL.md (branch feat/person-account-linking).
Status verified against the current code, not the audit text.

## Audit items
- [x] 1. gen_docs --check guard (fixed before this branch)
- [x] 2. SettingsView double import (fixed)
- [x] 3. System/security menu grouping (fixed)
- [x] 4. one-shot `migrate` service in docker-compose.yml; api/worker/backup depend on it (already present)
- [x] 5. packages/web-kit/package-lock.json is tracked (already present)
- [ ] 6. authFetch: 2 real call sites left (AdminSession CSV export, ReportsParts CSV download). Blob/CSV downloads cannot use the JSON typedClient; kept on purpose.
- [x] 7. mypy covers all of `melorin` (362 files); 3 new errors on this branch fixed
- [x] 8. dead code: CursorResult import is used for typing; `initiator` is a SQLAlchemy event parameter (`_initiator`)
- [x] 9. bandit B104 annotated with `# nosec B104` and reason; bandit -ll is clean
- [x] 10. ops_watch.sh unused APP removed; melorin.sh SC2097/SC2098 not reproducible: shellcheck not installable here
- [x] 11. large panel files: all now under 540 lines
- [x] 12. no skipped Playwright specs remain in e2e/tests
- [x] 13. decided in r15/r17: stays infrastructure-only (docs/06-ARCHITECTURE-DECISIONS.md)
- [x] 14. decided in r15/r17: stays in the system area (docs/06-ARCHITECTURE-DECISIONS.md)

## Account-linking (doc 25 "remaining")
- [x] A. Site UI: dashboard tab "linked accounts" + landing section (store-web, 4 tests)
- [x] B. Telegram bot: always-visible main-menu button + screen (3 tests). Needs a real bot token to try live.
- [x] C. HTTP and financial tests for consolidation (5 tests) and reauth/unlink (4 tests)
- [x] D. Reauth for passwordless users: e-mail one-time code. Telegram/Google-only accounts without e-mail keep session proof + last-method guard (product decision pending, see below)
- [x] E. decided: session proof + last-method guard for accounts with no password and no e-mail (docs/06-ARCHITECTURE-DECISIONS.md); a stronger proof is future work
- [x] F. README.fa.md has no matching identity row, nothing to mirror

## Cannot be verified here
Docker/Compose (no docker on the test server), real Telegram bots, payment gateways, PasarGuard, TLS/Caddy.


## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).

### Update 2026-11-16: large admin-web files / به‌روزرسانی فایل‌های بزرگ

- EN: pure moves, no behaviour change. `BundleDrawer` 695 to 397 (`BundlePackages`, `ResellerPrices`), `PanelDrawer` 648 to 505 (`panelForm.ts`), `PanelsView` 563 to about 440 (`panelsList.ts` pure list logic, `PanelsOverlays`), `ProductParts` 533 to 225 (`ProductDrawer`, `ProductSwitches`), `ReportsSections` 519 to 168, `ButtonStylesView` 508 to 222, `IdentityReviewsView` 483 to 162, `ResellerApplicationsView` 468 to 194. Second pass: `PanelDrawer` to 374 (`PanelConnectionSection`, `PanelCredentialsSection`), `ReceiptReviewPanel` to 376 (`ReceiptRow`, `receiptHelpers.ts`), `ReportCharts` to 61 (`CompareChart`, `DistributionCharts`), `AdminTeamParts` to 112 (`InviteDrawer`, `AdminDrawer`). No admin-web file is above 450 lines now.
- FA: جابه‌جایی خالص بدون تغییر رفتاری انجام شد (اعداد بالا). بعد از دومین مرحله هیچ فایل admin-web بزرگ‌تر از ۴۵۰ خط نیست.

### Verification run r22 (2026-11-16, Ubuntu 24.04, Python 3.12, Node 22, Docker 29.1, PostgreSQL 16, Redis 7) / گزارش اجرای اعتبارسنجی

| Control | Result |
|---|---|
| API suite (not integration, not concurrency) | 2708 passed, 1 skipped |
| integration + concurrency markers (PostgreSQL 16 + Redis 7) | 12 passed, 1 skipped |
| `alembic upgrade head` on an empty database, `alembic check`, baseline PostgreSQL test (upgrade, downgrade, upgrade) | passed, no drift |
| ruff check/format, mypy (384 files), import-linter (8 contracts), `gen_docs --check` | clean |
| admin-web tsc, eslint (max-warnings 0), vitest | 42 files / 309 tests passed; `vite build` ok |
| Playwright E2E (Chromium, mocked API) | 24 passed, 2 skipped (they need a seeded staging stack) |
| `docker compose up --build` postgres, redis, migrate, api on an empty volume | migrate reached `0001_initial_baseline`; api container healthy, `/healthz` 200 |

Still not run: real PasarGuard/Sanaei panels, real Telegram bots, Zarinpal, Caddy + Prometheus/Alertmanager profile, backup restore drill from S3.

### Audit closure 2026-11-19 (V-AUDIT V-001…V-032 + V01 report V-01…V-40) / بستن ممیزی

| Area | Status |
|---|---|
| Input handling / auth (V-001, V-002, V-003, V-015, V-016, V-017, V-018, V-019; V01 V-07, V-08, V-12, V-14) | Done: ASCII-normalised digits + byte-wise compares, dummy-hash timing, parameterised scrypt + rehash, JWT `iss/aud/jti/kid`, per-(e-mail, IP) throttle, /64 IPv6 keys, 503 on Redis/DB outage, `MultiFernet` + re-encrypt CLI |
| Payments (V01 V-15…V-25, V-30; V-022) | Done: destination whitelist (no secret echoed), no lock across the gateway call, refunded payments cannot be resurrected, refund finalisation parks in `manual_review` on inconsistent books, provisional credit needs a proof signal and cannot be rejected around, savepoint around the outbox insert, per-store OCR cap |
| Outbound safety (V-011…V-014, V-021) | Done: one `netpolicy` module, pinned webhook delivery, non-blocking DNS, counted failures |
| Observability (V-005, V-006, V-007, V-026) | Done: `MelorinApiDown` / `MelorinAlertSeriesAbsent`, idle main bot, ops-watch template, and (this pass) `scripts/host_watch.sh` out-of-stack watchdog + install-time receiver warning |
| Installer / ops (V-004, V-008, V-009, V-010, V-020, V-025, V-027, V-028, V-030, V-032; V01 V-02, V-04, V-32, V-32a, V-33…V-37, V-40) | Done |
| Tests (V-031) | PostgreSQL lane run in full: `tests/postgres` 12 passed / 0 skipped (with `TEST_PG_ADMIN_URL`), whole API suite on PostgreSQL 2811 passed / 1 skipped, SQLite lane 2798 passed / 11 skipped, Telegram main bot 104 passed |
| V-023 / V-024 (partial) | Done: weekly Trivy scan + Dependabot, `cap_drop`/`read_only`/no-new-privileges on db, cache and web containers, configurable bridge subnet. **Still open (needs a live Docker host):** `nginx-unprivileged` + refreshed digests, per-service `env_file` narrowing, first real `docker compose up` with the new cap sets |
| Verification pass 2026-11-19 (branch `fix/audit-remediation-v2`) | Re-run on a clean checkout: ruff check/format clean, mypy 387 files clean, import-linter 8/8, API suite (SQLite lane) 2814 passed / 11 skipped, admin-web 310 and store-web 83 vitest tests passed, tsc and eslint (max-warnings 0) clean for both SPAs. Probes: Persian/Arabic-Indic/full-width TOTP digits no longer raise; `netpolicy.is_forbidden_ip` blocks CGNAT (incl. 100.100.100.200), NAT64, 6to4, Teredo, mapped IPv4, link-local, benchmarking and reserved ranges while public v4/v6 stay allowed. V-023 / V-024 are skipped on request. Live run on the test server (2 vCPU / 4 GB, Docker 29): the Compose stack (postgres, redis, migrate, api with 2 workers, worker, both web images) came up healthy under the new `cap_drop` / `read_only` sets, `scripts/e2e_smoke.py` passed in full (wallet, order, provisioning, store isolation, rotating-XFF login throttle), `scripts/load_probe.py` p95 386 ms with 0 errors, Playwright (Chromium) 24 passed / 2 skipped (they need a seeded staging stack). The smoke probe was aligned with the V-017 design (hard per-e-mail ceiling of 100, so it now sends 130 rotating-XFF attempts). Not run: real panels, bots and gateways, the Caddy/Prometheus/Alertmanager profile |
| **Open by decision** | V-029: generated patch files remain in Git history (a history rewrite on a shared repository needs an explicit go-ahead; the gitleaks allow-list is in place). V01 V-21 is closed: OCR runs in the worker (`payments.receipt_ocr`). V01 V-27: the single baseline `0001` is frozen the day the first real database exists; from then on only `0002_…` revisions (the baseline test pins the current single revision until that day). Not exercised: Playwright e2e, `e2e_smoke` on a Compose stack, real panels/bots/gateways |
