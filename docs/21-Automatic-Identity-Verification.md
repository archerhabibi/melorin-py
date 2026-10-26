# 21 — Automatic identity verification (website login through the Telegram bot)

Goal: the identity check of a returning visitor needs **no manual step** whenever it is safe to skip one, and the
manual step that remains is exactly the number-match confirmation of `TELEGRAM-WEB-LOGIN.md`.

## Three levels, decided by the server

| level    | when                                                                                   | what the visitor does                         |
|----------|----------------------------------------------------------------------------------------|-----------------------------------------------|
| `silent` | known browser **and** same network (/24 IPv4, /48 IPv6) **and** seen within the silent window | nothing: signed in when the page opens        |
| `auto`   | known browser, any network, inside the trust window                                    | opens the bot link; that is the whole approval |
| `manual` | unknown / expired / revoked browser                                                    | number match in the bot (unchanged)           |

A manual approval is what *earns* trust (`remember`, default on). Trust is per store and per Telegram account.

## The device key
* Minted by the **server** (`secrets.token_urlsafe(32)`) and kept by the browser in the **HttpOnly** cookie `melorin_dk`
  (`Secure` outside development, `SameSite=Lax`, path `/api/v1/auth/telegram/web`). Page scripts and any XSS cannot read it,
  and the storefront stores nothing in `localStorage`/`sessionStorage`.
* The database stores only `SHA-256("trusted-device:" + key)` (`trusted_devices.key_hash`, unique).
* A relayed phishing link cannot reach `auto`/`silent`: the attacker's browser does not hold a key the victim approved.
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

## Settings
`TELEGRAM_WEB_LOGIN_TRUST_DAYS` (default 60, `0` turns automatic verification off) and `TELEGRAM_WEB_LOGIN_SILENT_DAYS`
(default 14, `0` disables only the silent level).

## Housekeeping
`telegram_login_gc_job` (`web.purge_old`) removes finished login sessions a day after expiry and trusted devices 30 days after
they expired or were revoked.

## Tests
`apps/api/tests/test_identify_trusted_devices.py` (levels, per-store isolation, anti-phishing, revocation, cap, purge, cookie over HTTP),
`test_p01_telegram_web_login*.py` (flow and bot side).
