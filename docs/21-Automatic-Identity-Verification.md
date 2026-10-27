# 21 — Automatic identity verification (website login through the Telegram bot)

Goal: the identity check of a returning visitor needs **no manual step** whenever it is safe to skip one, and the
manual step that remains is exactly the number-match confirmation of `TELEGRAM-WEB-LOGIN.md`.

## Three levels, decided by the server

| level    | when                                                                                   | what the visitor does                         |
|----------|----------------------------------------------------------------------------------------|-----------------------------------------------|
| `silent` | known browser **and** same network (/24 IPv4, /48 IPv6) **and** same browser/OS family **and** seen within the silent window | nothing: signed in when the page opens        |
| `auto`   | known browser, any network, inside the trust window                                    | opens the bot link; that is the whole approval |
| `manual` | unknown / expired / revoked browser                                                    | number match in the bot (unchanged)           |

A manual approval is what *earns* trust (`remember`, default on). Trust is per store and per Telegram account.

## The device key
* Minted by the **server** (`secrets.token_urlsafe(32)`) and kept by the browser in the **HttpOnly** cookie `melorin_dk`
  (`Secure` outside development, `SameSite=Lax`, path `/api/v1/auth/telegram/web`). Page scripts and any XSS cannot read it,
  and the storefront stores nothing in `localStorage`/`sessionStorage`.
* The database stores only `SHA-256("trusted-device:" + key)` (`trusted_devices.key_hash`, unique).
* A relayed phishing link cannot reach `auto`/`silent`: the attacker's browser does not hold a key the victim approved.
* A device key replayed from a different browser/OS family (e.g. Chrome key used by Firefox) never gets `silent`; it gets `auto`, and the owner's approval refreshes the stored label.
* A key approved for one account is never re-bound to another (`device_account_mismatch`).

## Account rules are shared
`web._complete` is the single approval point for both paths, so disabled accounts, closed registration and the
"admins use the admin panel" rule apply identically to automatic and manual verification. A silent attempt for an account that is
no longer eligible revokes the device and falls back to the manual path (which explains the refusal).

## Owner control
* Every automatic login sends the owner a Telegram notice (deduplicated per device per day).
* `/devices` in the bot lists trusted browsers; each can be removed; **"this was not me"** revokes all devices of that Telegram
  account in that store **and** its web refresh tokens at once.
* The browser can drop its own trust with `POST /auth/telegram/web/devices/forget` (cookie is the proof).
* Limits: at most 10 live devices per account (oldest make room), sliding expiry, rate-limited endpoints, audit events on every step.

## Identity-link conflicts settle themselves
The same verified identity (e-mail, Google, Telegram) on two accounts used to wait in the admin review queue. Now
`modules/identity/auto_link.py` decides with the pure rule in `domain/identity_auto_link.py`:

| situation | result |
|---|---|
| one account is an **empty shell** (no orders, payments, VPN accounts, tickets, referral, store, non-zero wallet or ledger history, no password, no 2FA, not admin) | the shell is folded into the other account: identities, e-mail, trusted devices and store memberships move, its sessions end, it is deactivated and archived (never deleted) |
| both are shells | the older account lives on |
| **both hold records**, either is inactive or an admin, or several candidates | never merged: stays in the admin queue (`/admin/identity-link-reviews`) |

* "Empty shell" is decided from the **schema itself** (every foreign key to `users.id` outside a short disposable list), so a
  table added later protects its rows without anyone updating a list.
* Proof of ownership comes from the flow that raised the conflict (e-mail code, verified Google token, bot link code).
* From a shell's own session the merge ends that session and the API answers `IDENTITY_MERGED` (409): sign in again.
* Audit: `identity.auto_merged` (audit log) and `identity_auto_merged` (security event); the review row stays with status
  `linked`, no resolver and note `auto:<rule>`.
* `identity_auto_link_job` (worker, every 10 minutes) settles reviews that became safe after they were queued.
* Switch: `IDENTITY_AUTO_LINK` (default `true`; `false` = every conflict waits for an admin).

## Reseller applications verify themselves
A reseller application brings two identifiers (store domain, Telegram bot). Both are now proven by Core on a schedule
(`modules/reseller/auto_verify.py`), so the admin only decides *whether* to approve, never *whether the data is real*.

| check | how | retry |
|---|---|---|
| bot | `getMe` with the stored token; a Telegram outage no longer leaves the bot "unverified" for an admin to click | back-off 2 min, 5 min, 15 min, 1 h, then every 6 h |
| domain control | DNS TXT `_melorin-verify.<domain>` = `melorin-verify=<code>` **or** file `https://<domain>/.well-known/melorin-verify.txt` with the same content | same schedule; applicant can press "verify now" (6 per 5 min) |

* `<code>` is `HMAC(jwt_secret, application id + domain)`: nothing extra is stored, a code from another application or
  another domain never matches, and the applicant reads it from `GET /reseller/applications/{id}/verification`.
* DNS is read through DNS-over-HTTPS (no new dependency); the HTTP proof refuses hosts that resolve to private/loopback
  addresses (SSRF) and never follows redirects. Both only read.
* When bot **and** domain are proven, admins get one notification ("ready to decide") and the audit log records
  `reseller.application_auto_verified`. The admin list shows `domain_verified`, `auto_verified`, `verify_error`, `verify_next_at`.
* Retry window: `RESELLER_VERIFY_WINDOW_DAYS` (default 7) after filing; "verify now" opens a fresh window.
* Switches: `RESELLER_AUTO_VERIFY` (default `true`), `RESELLER_REQUIRE_DOMAIN_PROOF` (default `false`; `true` = approval of an
  application whose domain is not proven is refused with `DOMAIN_PROOF_REQUIRED`).
* Worker job `reseller_auto_verify_job` (every 2 minutes); migration `0034`.
* Tests: `apps/api/tests/test_identify_reseller_auto_verify.py`.

## Reseller approval can be automatic (opt-in)
`modules/reseller/auto_approve.py`. When bot **and** domain are proven, the only open question left for an admin is "do we want
this reseller at all". An operator who has decided that in advance sets `RESELLER_AUTO_APPROVE=true` (**default `false`**: it grants a store)
and the application approves itself through the same `create_reseller_store` code as the manual path.

| guard rail (any miss = stays for an admin, nothing is ever rejected automatically) | |
|---|---|
| status `pending`, details present, bot **and** domain verified | |
| applicant active, not guest, not admin, account older than `RESELLER_AUTO_APPROVE_MIN_ACCOUNT_DAYS` (7) | |
| target store active, applicant still an active member, no reseller store for that pair yet | |
| domain and bot still free (`ensure_identity_free`, same as manual) | |
| debt limit is the fixed `RESELLER_AUTO_APPROVE_DEBT_LIMIT` (default 0: the reseller pays before it sells) | |

All-or-nothing (savepoint). Audit `reseller.application_auto_approved` (actor `system`), `review_reason = auto:fully_proven`,
`auto_approved = true` in the admin list; the owner gets the usual approval notice and admins get "approved automatically".

## Approved resellers keep proving who they are
`modules/reseller/recheck.py`, worker `reseller_identity_recheck_job` (every 30 min; each store is due every `RESELLER_RECHECK_HOURS`, 24).
Re-checks (only reads): the DNS/well-known domain proof is still there (when it was proven), and the store's bot token is still accepted by
Telegram **and** is still the same bot.

| round result | effect |
|---|---|
| all good | failures reset; if the identity was lost, admins are told it recovered |
| failed round 1 | owner gets a warning; retry in 6 h (one DNS hiccup proves nothing) |
| `RESELLER_RECHECK_FAIL_LIMIT` (3) consecutive failed rounds | `identity_lost_at` set, audit `reseller.identity_lost`, admins and owner notified; store suspended **only if** `RESELLER_RECHECK_SUSPEND=true` (default `false`) |
| Telegram unreachable | neutral: no failure, retry in 1 h |

Recovery never un-suspends a store by itself; that stays an admin decision. Suspended stores are not re-checked. Migration `0035`
also schedules the first re-check of already-approved stores that proved their domain.
Admin list fields: `auto_approved`, `recheck_failures`, `recheck_error`, `recheck_next_at`, `identity_lost`.
Switches: `RESELLER_AUTO_APPROVE`, `RESELLER_AUTO_APPROVE_DEBT_LIMIT`, `RESELLER_AUTO_APPROVE_MIN_ACCOUNT_DAYS`, `RESELLER_RECHECK`,
`RESELLER_RECHECK_HOURS`, `RESELLER_RECHECK_FAIL_LIMIT`, `RESELLER_RECHECK_SUSPEND`. Tests: `apps/api/tests/test_identify_reseller_lifecycle.py`.

## Admin screen «هویت» (one screen, three tabs)
Panel → سیستم → «هویت» (`apps/admin-web/src/IdentityHubView.jsx`; deep link `#/identity?tab=review|auto|devices`, the old
`#/identity-auto` bookmark opens the devices tab). It replaces the two former menu entries «بررسی هویت» and «هویت خودکار», which
overlapped: conflicts Core settled itself were visible in both.

| tab | content | who acts |
|---|---|---|
| **نیاز به بررسی** | the manual queue (`IdentityReviewsView`, `/admin/identity-link-reviews`): conflicts Core could not settle. The tab shows the number of open ones | an admin decides |
| **انجام‌شده خودکار** | automatic merges (read-only report, see below) | nobody |
| **دستگاه‌های مورداعتماد** | trusted browsers, revoke one / the whole account (see below) | an admin may revoke |

Rows settled by Core (`resolution_note` starting with `auto:`) carry `auto: true` in `GET /admin/identity-link-reviews` and are
hidden from the manual queue (also from its «متصل شده» / «همه» counters); they appear only in «انجام‌شده خودکار».
`IdentityAutoView` is reused by the hub with `section="merges"` / `section="devices"`. Backing code: `modules/admin/identity_auto.py`:

* **Trusted devices** (`GET /admin/trusted-devices?status=active|expired|revoked|all&q=&store_id=`): owner, store, browser label,
  Telegram id, last network, uses, last seen, expiry. Search by name, e-mail, label or Telegram id. The device key and its hash
  are never returned.
* **Revoke**: one device (`POST /admin/trusted-devices/{id}/revoke`) or every live device of one account
  (`POST /admin/trusted-devices/revoke-account`). The next login from those browsers needs the manual number match again.
  The account's web sessions are not touched (the owner's own "this was not me" in the bot also ends them). Both are audited
  (`trusted_device.revoked_by_admin`, `trusted_device.account_revoked_by_admin`).
* **Automatic merges** (`GET /admin/identity-auto-merges?days=`): read from `identity.auto_merged` audit events, with a card of the
  kept account and of the archived empty shell, the rule and the providers moved.
* **Summary** (`GET /admin/trusted-devices/summary`): live devices, accounts with devices, revoked devices, merges in 30 days.
* Tests: `apps/api/tests/test_identify_admin_overview.py`, `apps/admin-web/tests/identity-auto.test.jsx`.

## Settings
`TELEGRAM_WEB_LOGIN_TRUST_DAYS` (default 60, `0` turns automatic verification off) and `TELEGRAM_WEB_LOGIN_SILENT_DAYS`
(default 14, `0` disables only the silent level).

## Housekeeping
`telegram_login_gc_job` (`web.purge_old`) removes finished login sessions a day after expiry and trusted devices 30 days after
they expired or were revoked.

## Tests
`apps/api/tests/test_identify_trusted_devices.py` (levels, per-store isolation, anti-phishing, revocation, cap, purge, cookie over HTTP),
`test_identify_auto_link.py` (merge rule, shell detection, flows, sweep, worker job), `test_p01_telegram_web_login*.py` (flow and bot side).
