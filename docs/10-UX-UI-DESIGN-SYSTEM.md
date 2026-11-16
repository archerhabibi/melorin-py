# سیستم طراحی UX/UI / UX/UI Design System

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** الگوهای UI مشترک و قواعد تجربهٔ کاربری.

هر Feature فقط UI و تعامل خودش را دارد و منطق کسب‌وکار را پیاده نمی‌کند. همهٔ درخواست‌ها از `typedClient` (`apps/admin-web/src/api`) عبور می‌کنند؛ فقط دانلود CSV خام استثناست. اجزای مشترک در `apps/admin-web/src/shared` (kit، types) هستند. فایل‌های بزرگ (>۴۵۰ خط) باید به اجزای کوچک‌تر بدون تغییر رفتار تقسیم شوند (نک. [21](21-ROADMAP-TECHNICAL-DEBT.md)).

## English section

**Purpose:** Shared UI patterns and UX rules.

Each feature owns only its UI and interaction and never implements business logic. All requests go through `typedClient` (`apps/admin-web/src/api`); only raw CSV downloads are exempt. Shared components live in `apps/admin-web/src/shared` (kit, types). Large files (>450 lines) should be split into smaller components without behaviour change (see [21](21-ROADMAP-TECHNICAL-DEBT.md)).

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
