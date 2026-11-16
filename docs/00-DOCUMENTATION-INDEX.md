# فهرست مستندات / Documentation Index

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** نقطهٔ ورود مستندات و نقشهٔ موضوعات: هر موضوع یک مرجع اصلی دارد و بقیه فقط خلاصه و لینک می‌دهند.

**نقشه:** 01 محصول؛ 02–04 نیازمندی، واژه‌نامه و قواعد؛ 05–07 معماری، تصمیم‌ها و مدل داده؛ 08 هویت؛ 09–10 پنل و UX؛ 11–12 API و امنیت؛ 13–17 کاتالوگ، سفارش، مالی، ارتباطات و یکپارچه‌سازی؛ 18–20 عملیات، دیتابیس و کیفیت؛ 21 نقشه راه و بدهی.

**قواعد نگارش:** هر سند ابتدا فارسی و سپس انگلیسی؛ اصطلاحات فنی و مسیرها به شکل اصلی؛ وضعیت کد فعلی بر گزارش قدیمی اولویت دارد؛ تصمیم جدید کاربر بر قدیم مقدم است و قدیمی در سند 06 با علت ثبت می‌شود.

**اسناد تولیدشده:** `docs/STATUS.md` و `docs/API.md` از `python scripts/gen_docs.py` می‌آیند (ورودی: کد و OpenAPI)؛ دستی ویرایش نشوند و در این شمارش ۲۲ سند نمی‌آیند. بررسی انحراف: `gen_docs.py --check`.

**به‌روزرسانی:** با هر تغییر رفتاری، سند مرجع همان موضوع و تاریخ «آخرین بازبینی» همان سند به‌روز می‌شود.

## English section

**Purpose:** the entry point and topic map: each topic has one primary reference and the rest only summarise and link.

**Map:** 01 product; 02–04 requirements, glossary, rules; 05–07 architecture, decisions, data model; 08 identity; 09–10 admin panel and UX; 11–12 API and security; 13–17 catalog, orders, finance, communication, integrations; 18–20 operations, database, quality; 21 roadmap and debt.

**Writing rules:** each document is Persian first, then English; technical terms and paths keep their original form; current code beats an old report; a new user decision beats an old one and the old one is recorded with its reason in doc 06.

**Generated docs:** `docs/STATUS.md` and `docs/API.md` come from `python scripts/gen_docs.py` (inputs: code and OpenAPI); they are not edited by hand and not counted in the 22 canonical documents. Drift check: `gen_docs.py --check`.

**Updating:** with every behaviour change, update the reference document of that topic and its "last review" date.

## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `00-DOCUMENTATION-INDEX.md`

#### Melorin — فهرست اسناد
نسخه 1.1 | به‌روزرسانی‌شده بر اساس پاسخ‌های مالک محصول در 2026-10-09. این بسته شامل نیازمندی‌ها، طراحی و تصمیم‌های ثبت‌شده است؛ تصمیم‌های باقی‌مانده فقط در سند 10 فهرست شده‌اند.
1. 02-REQUIREMENTS-SRS.md — سند جامع نیازمندی‌ها
2. 05-SYSTEM-ARCHITECTURE.md — معماری
3. 04-BUSINESS-RULES.md — طراحی فنی
4. 07-DOMAIN-DATA-MODEL.md — مدل دامنه و داده
5. 11-API-CONTRACTS.md — API و Webhook
6. 12-SECURITY-AUTHORIZATION.md — امنیت و مجوزها
7. 14-ORDERS-VPN-PROVISIONING.md — مالی، Wallet-first checkout، Coupon، سفارش و Provisioning
8. 18-OPERATIONS-DEPLOYMENT-DR.md — استقرار و بازیابی
9. 20-TESTING-QUALITY-RELEASE.md — تست و کیفیت
10. 21-ROADMAP-TECHNICAL-DEBT.md — نقشه راه و تصمیم‌های باز باقی‌مانده
11. 16-COMMUNICATION-SUPPORT.md — مشخصات کانال‌ها

مرجع نیازمندی‌ها: سند 01. قوانین مالی و چرخه سفارش: سند 07. معماری: سند 02. تصمیم‌های قطعی و موارد باز در سند 10 تفکیک شده‌اند. همه خریدها Wallet-first هستند؛ کیف پول، ارز و مقصد پرداخت Store-scoped است. Reseller باید پیش از فعال‌سازی مشتری Main Store باشد. ARQ + Redis، Reseller API و Outgoing Webhook در V1 مصوب‌اند.

واژه‌نامه (معنی دقیق «Core»، `melorin.core`، `domain`، job، store): `03-GLOSSARY.md`.

اسناد تکمیلی: 13-Renewal-Core-Design · 14-Store-Isolation-Design (شامل Rollout) · 16-Channel-Binding-Design · 17-Referral-Coupon-Store-Scope (بخش رفرال ← 21-Store-Scoped-Referral-Coupons) · 18-Telegram-Event-Center-Design · 19-Upstream-Bot-Adapter · 20-Card-Receipt-Auto-Verification · 22-Customer-Loyalty-Club · 23-Automatic-Identity-Verification (پیش‌تر 21؛ شمارهٔ ۲۱ فقط برای Store-Scoped-Referral-Coupons است؛ شماره‌های 12 و 15 عمداً بدون سند و رزرو هستند). تصمیم‌های اعمال‌شدهٔ v1.1 در `06-ARCHITECTURE-DECISIONS.md`؛ راه‌اندازی ورود با گوگل/تلگرام در `08-IDENTITY-ACCOUNT-PERSON.md` و `08-IDENTITY-ACCOUNT-PERSON.md`؛ پشتیبان‌گیری در 08؛ دامنهٔ تلگرام و طراحی ربات نماینده در 11؛ بازطراحی صفحه‌های زیرساخت در 03؛ جمع‌آوری شواهد اجرا در `20-TESTING-QUALITY-RELEASE.md`.
وضعیت اندازه‌گیری‌شدهٔ پروژه (هد مایگریشن، تعداد API/تست) فقط در `docs/STATUS.md` (تولید خودکار) و فهرست مسیرها در `docs/API.md` است. گزارش‌های فازهای قبلی در `docs/06-ARCHITECTURE-DECISIONS.md` نگهداری می‌شوند و وضعیت جاری نیستند. سیاست: `docs/00-DOCUMENTATION-INDEX.md`.

### منبع / Source: `00-DOCUMENTATION-INDEX.md`

#### Documentation policy

**Current guidance** lives in `README.md`, `README.fa.md`, `docs/18-OPERATIONS-DEPLOYMENT-DR.md`, the numbered design documents
`docs/01`-`docs/17`, `docs/06-ARCHITECTURE-DECISIONS.md`, and the release evidence matrix (`docs/20-TESTING-QUALITY-RELEASE.md`,
the only release-status source).

**Machine-owned files** - `docs/STATUS.md` and the route tables in `docs/API.md` - are generated by
`python scripts/gen_docs.py` and verified by `python scripts/gen_docs.py --check` (part of `make guards`,
the quality gate and CI). Never hard-code the Alembic head, test counts, coverage or route lists anywhere else.

**History**: phase reports, completion notes and audits are *not* kept in the working tree. They are preserved in the
git tag `docs-history-2026-10-22` and indexed in `docs/06-ARCHITECTURE-DECISIONS.md` (how to read them is described there). `docs/history/`
holds only the four files that tests and guards read (`I33`, `I39`, `I40`, `I41`); the guard rejects any other file there
and any phase report in `docs/` root. A new report belongs in the commit message / `docs/06-ARCHITECTURE-DECISIONS.md`, not in a new file.
Reports are evidence of what changed, not active instructions. Keep one document per subject: bilingual guides are one file
with an English and a Persian section.

When a setting, route, install step or security rule changes, update the English and Persian README plus the runbook
in the same change, then run `python scripts/gen_docs.py`. Do not store tokens, passwords, TOTP seeds, age identities,
or provider credentials in reports.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).

## نقشه اسناد / Document map

| # | سند / Document | موضوع / Topic |
|---|---|---|
| 00 | [00-DOCUMENTATION-INDEX.md](00-DOCUMENTATION-INDEX.md) | فهرست مستندات / Documentation Index |
| 01 | [01-PRODUCT-OVERVIEW.md](01-PRODUCT-OVERVIEW.md) | مرور محصول / Product Overview |
| 02 | [02-REQUIREMENTS-SRS.md](02-REQUIREMENTS-SRS.md) | نیازمندی‌ها (SRS) / Requirements (SRS) |
| 03 | [03-GLOSSARY.md](03-GLOSSARY.md) | واژه‌نامه / Glossary |
| 04 | [04-BUSINESS-RULES.md](04-BUSINESS-RULES.md) | قواعد کسب‌وکار / Business Rules |
| 05 | [05-SYSTEM-ARCHITECTURE.md](05-SYSTEM-ARCHITECTURE.md) | معماری سیستم / System Architecture |
| 06 | [06-ARCHITECTURE-DECISIONS.md](06-ARCHITECTURE-DECISIONS.md) | تصمیم‌های معماری / Architecture Decisions |
| 07 | [07-DOMAIN-DATA-MODEL.md](07-DOMAIN-DATA-MODEL.md) | مدل داده و دامنه / Domain & Data Model |
| 08 | [08-IDENTITY-ACCOUNT-PERSON.md](08-IDENTITY-ACCOUNT-PERSON.md) | هویت، حساب و شخص / Identity, Account & Person |
| 09 | [09-ADMIN-UI-ARCHITECTURE.md](09-ADMIN-UI-ARCHITECTURE.md) | معماری پنل ادمین / Admin UI Architecture |
| 10 | [10-UX-UI-DESIGN-SYSTEM.md](10-UX-UI-DESIGN-SYSTEM.md) | سیستم طراحی UX/UI / UX/UI Design System |
| 11 | [11-API-CONTRACTS.md](11-API-CONTRACTS.md) | قراردادهای API / API Contracts |
| 12 | [12-SECURITY-AUTHORIZATION.md](12-SECURITY-AUTHORIZATION.md) | امنیت و مجوزها / Security & Authorization |
| 13 | [13-CATALOG-STORE-RESELLER.md](13-CATALOG-STORE-RESELLER.md) | کاتالوگ، فروشگاه و نمایندگی / Catalog, Store & Reseller |
| 14 | [14-ORDERS-VPN-PROVISIONING.md](14-ORDERS-VPN-PROVISIONING.md) | سفارش، VPN و Provisioning / Orders, VPN & Provisioning |
| 15 | [15-PAYMENTS-WALLET-FINANCE.md](15-PAYMENTS-WALLET-FINANCE.md) | پرداخت، کیف پول و مالی / Payments, Wallet & Finance |
| 16 | [16-COMMUNICATION-SUPPORT.md](16-COMMUNICATION-SUPPORT.md) | ارتباطات و پشتیبانی / Communication & Support |
| 17 | [17-INTEGRATIONS-PROVIDERS.md](17-INTEGRATIONS-PROVIDERS.md) | یکپارچه‌سازی‌ها و Providerها / Integrations & Providers |
| 18 | [18-OPERATIONS-DEPLOYMENT-DR.md](18-OPERATIONS-DEPLOYMENT-DR.md) | عملیات، استقرار و DR / Operations, Deployment & DR |
| 19 | [19-DATABASE-MIGRATIONS.md](19-DATABASE-MIGRATIONS.md) | پایگاه داده و مهاجرت‌ها / Database & Migrations |
| 20 | [20-TESTING-QUALITY-RELEASE.md](20-TESTING-QUALITY-RELEASE.md) | تست، کیفیت و انتشار / Testing, Quality & Release |
| 21 | [21-ROADMAP-TECHNICAL-DEBT.md](21-ROADMAP-TECHNICAL-DEBT.md) | نقشه راه و بدهی فنی / Roadmap & Technical Debt |

## اسناد تولیدشده / Generated documents

`docs/STATUS.md` و `docs/API.md` توسط `python scripts/gen_docs.py` تولید می‌شوند (از کد، مدل‌ها و OpenAPI) و جزو ۲۲ سند نگارش‌دستی نیستند؛ آن‌ها را دستی ویرایش نکنید. / `docs/STATUS.md` and `docs/API.md` are generated by `python scripts/gen_docs.py` and are not part of the 22 hand-written documents; do not edit them by hand.
