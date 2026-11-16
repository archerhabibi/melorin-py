# معماری پنل ادمین / Admin UI Architecture

> **وضعیت / Status:** مرجع جاری / Current canonical
> **آخرین بازبینی / Last review:** 2026-11-16
> **فهرست / Index:** [00](00-DOCUMENTATION-INDEX.md)

## بخش فارسی

**هدف:** گروه‌های پنل، منوها، مجوزها و Hubها.

**هشت گروه منو (حفظ‌شده):** نمای کلی؛ فروش و عملیات؛ مشتریان (کاربران، هویت)؛ فروشگاه‌ها و نمایندگان؛ کاتالوگ و بازاریابی؛ زیرساخت و عملیات پنل؛ اعلان‌ها، ارتباطات و پشتیبانی (Broadcast، Event Center، تیکت‌ها)؛ سیستم و امنیت (تنظیمات، دکمه‌های تلگرام با مجوز `system`، ممیزی، تیم، حساب من). انتقال تیکت‌ها فقط جابه‌جایی UI است؛ دامنهٔ Tickets در بک‌اند مستقل می‌ماند. Store Hub و Panel Operations Hub حفظ می‌شوند. منبع حقیقت منو: `apps/admin-web/src/app/adminNav.ts` و تست‌های `nav-structure` / `nav-role-matrix`.

**ماتریس مجوز (`domain/admin_access.py`):** هر نقش برای هر ناحیه `r` یا `rw` دارد؛ مسیر ناشناخته به ناحیهٔ `system` (فقط owner) می‌افتد و نقش نامعتبر هیچ دسترسی ندارد. `owner`: همهٔ نواحی rw. `manager`: نواحی عملیاتی rw، audit فقط خواندنی. `finance`: orders و payments rw، بقیه خواندنی. `support`: customers و support rw، بقیه خواندنی. `viewer`: همه خواندنی. تأیید یکپارچه‌سازی کیف پول سطح `payments` است. دکمه‌های تلگرام (`admin/telegram`) در ناحیهٔ `system` و در گروه «سیستم و امنیت» می‌مانند، یعنی عمداً فقط owner؛ این تصمیم قطعی است و دیگر «تصمیم باز» نیست. عملیات گروهی روی پنل فقط ناحیهٔ `infrastructure` است.

## English section

**Purpose:** Panel groups, menus, permissions and hubs.

**Eight menu groups (kept):** Overview; Sales & Operations; Customers (users, identity); Stores & Resellers; Catalog & Marketing; Infrastructure & Panel Ops; Notifications, Communication & Support (Broadcast, Event Center, Tickets); System & Security (settings, Telegram buttons gated by the `system` permission, audit, team, my account). Moving Tickets is a UI-only change; the Tickets backend domain stays independent. Store Hub and Panel Operations Hub are kept. Source of truth for the menu: `apps/admin-web/src/app/adminNav.ts` and the `nav-structure` / `nav-role-matrix` tests.

**Permission matrix (`domain/admin_access.py`):** each role holds `r` or `rw` per area; an unknown path falls into `system` (owner only) and an unknown role has no access. `owner`: all areas rw. `manager`: operational areas rw, audit read-only. `finance`: orders and payments rw, the rest read-only. `support`: customers and support rw, the rest read-only. `viewer`: everything read-only. Approving a wallet consolidation is a `payments`-level write. The Telegram buttons (`admin/telegram`) stay in the `system` area and in the "System & Security" group, i.e. owner only on purpose; this is a settled decision, no longer open. Bulk panel operations are limited to the `infrastructure` area.

## مواد ادغام‌شده / Merged source material

> متن اصلی اسناد قبلی بدون حذف محتوا در این بخش حفظ شده است (هر متن به زبان اصلی خود). / Original text of the previous documents, preserved without dropping content (each in its original language).

### منبع / Source: `09-ADMIN-UI-ARCHITECTURE.md`

#### 24 - Admin team: roles and invitations

Status: implemented (migration `0055_admin_team`). Code: `domain/admin_access.py`, `domain/password_policy.py`,
`modules/identity/admin_team.py`, `modules/admin/admins.py`, `modules/identity/routes/admin_invite.py`; web: `AdminTeamView`, `AcceptInvite`, `MyAccountView`.

##### Model
Everyone who signs in to the admin panel has `users.is_super_admin = true` (the channel gate: password + TOTP).
What they may do is the role in `users.admin_roles`. The first known role wins; an empty or unknown list has **no access** (fail closed).
The migration gives every existing admin `owner`, so nobody loses access on upgrade.

##### Permission matrix (r = read, rw = read + write)
| Area | owner | manager | finance | support | viewer |
|---|---|---|---|---|---|
| overview, reports | rw | rw | r | overview r | r |
| orders | rw | rw | rw | r | r |
| payments | rw | rw | rw | r | r |
| catalog | rw | rw | r | r | r |
| infrastructure | rw | rw | - | - | r |
| resellers | rw | rw | r | - | r |
| customers | rw | rw | r | rw | r |
| support | rw | rw | - | rw | r |
| audit | rw | r | - | - | - |
| system (settings, integrations, flags) | rw | - | - | - | - |
| admins (this feature) | rw | - | - | - | - |
| self (own password, `/admin/me`) | rw | rw | rw | rw | rw |

##### Enforcement
* `require_admin_session` runs `admin_area_guard`: the request path maps to an area via the ordered `PATH_RULES` (first match wins);
  GET/HEAD = read, other methods = write; GETs that reveal secrets (panel credentials, service access, bank-SMS token) count as writes.
* A path no rule knows maps to `system` (owner only), so a new route is too strict, never too open.
* Store-context endpoints (reseller panel, loyalty, referrals) additionally need the matching resellers + catalog grants.
* Denials return 403 `ADMIN_ROLE_FORBIDDEN` and record the security event `admin_area_denied`.
* The web hides screens using `GET /admin/me` permissions, as a convenience only.

##### Invitation flow
1. The owner invites an e-mail + role: an inactive shell user plus a one-time token (256 bit, stored as SHA-256, 72 h, one live invite per user). The link is shown once and e-mailed when mail is configured; it lives in the URL fragment (`/#/accept-invite?t=...`).
2. The invitee opens it (`inspect`), starts enrolment (`enroll`: their own TOTP seed and QR), then `accept` with a password that passes the policy and one valid TOTP code. Five wrong codes lock the invite.
3. No session is issued; the invitee signs in through the normal password + TOTP login.
Public endpoints are rate limited (20 per 5 min per IP).

##### Safeguards
* Nobody can demote, suspend, remove or reset themselves; the last active owner is protected.
* Suspend, remove and reset-access revoke refresh tokens. A removed admin is archived (audit trail still resolves) and can be re-invited from scratch.
* Password policy: 12+ characters, not repetitive, not containing the e-mail name, not common, mixed character classes.
* Every change is written to the audit log; no secret is ever logged.

## منابع و ارجاع‌ها / References

- کد و تست‌های مرتبط در `apps/` و `scripts/`؛ سند فهرست: [00](00-DOCUMENTATION-INDEX.md).
