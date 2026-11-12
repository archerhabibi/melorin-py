# T06 — Melorin install report on a clean server (English)

Date: 2026-11-11 · Server: Ubuntu 22.04, 2 vCPU, 4 GB RAM, 40 GB disk (Hetzner) · Domains: `shop.88promax.ir` (store), `admin.88promax.ir` (admin)
Installed ref: `main` (commit `d7be664`; no release tag exists yet).

## 1. Summary
- Installed with the exact README one-liner; it **finished without errors** (about 5 minutes).
- All 12 containers are `healthy`; both domains answer 200 with a valid Let's Encrypt certificate; `ufw` (22/80/443), `fail2ban`, 2 GiB swap and the change recorder (`ops-watch`) are active.
- The pre-existing services on the host (MCP on port 8008 and the cloudflared tunnel) were left untouched.
- **One real defect found and fixed:** Alertmanager had no receiver, so alerts were never delivered (section 4).

## 2. How it was run
The README command was run; in the menu `1) Install` with the five answers (store domain, admin domain, admin e-mail, bot token, admin numeric Telegram ID). The installer checked DNS, installed Docker, built the images, ran migrations and bootstrap and printed its own verification: all `[ok]` except the reminder to copy the backup key off the server.

## 3. Post-install checks
| Item | Result |
|---|---|
| Containers (postgres, redis, api, worker, backup, store_web, admin_web, telegram_main, telegram_reseller, caddy, prometheus, alertmanager) | all healthy |
| `https://shop…` / `https://admin…` | 200, valid certificate |
| `/health`, `/healthz` | 200 |
| Telegram token | valid (getMe) |
| Footprint | about 500 MB RAM for the whole stack; disk 22% |
| Images | all pinned by digest |

## 4. Findings
| # | Finding | Severity | Status |
|---|---|---|---|
| F1 | **Alertmanager without a receiver:** the installer knows the bot token and the admin ID but never filled `ALERT_TELEGRAM_BOT_TOKEN` / `ALERT_TELEGRAM_CHAT_ID` in `.env`; log: "no alert receiver configured… Alerts will NOT be delivered". Every Prometheus alert was silently dropped. | Medium (operational) | **Fixed** (this branch) |
| F2 | Caddy's ACME contact e-mail is empty (certificate-expiry notices go nowhere). | Low | Not changed; proposed in T07/T08 |
| F3 | `get.docker.com` is piped to `sh` unpinned. | Low | Not changed; proposed in T07/T08 |
| F4 | Cosmetic Caddy warnings (Caddyfile formatting, UDP buffer for HTTP/3) | Info | Not changed |

**Correction of an earlier claim of mine:** in the first step I said the menu loops forever on EOF. That was **wrong**: my bad input (answers fed before choosing option 1) produced exactly 6 "Invalid choice" lines and the menu then exited via `exit 0` on EOF. It is not a bug and nothing was changed for it.

## 5. Changes in this branch (`fix/install-alert-receiver-t05`)
- `scripts/install_server.sh`: when both the bot token and the admin ID are supplied, `ALERT_TELEGRAM_BOT_TOKEN` and `ALERT_TELEGRAM_CHAT_ID` are set too.
- `melorin.sh`: changing the token or admin ID from the menu keeps the alert receiver in sync (unless a separate alert bot was configured on purpose).

**Live validation:** the same values were set in `.env`, Alertmanager was recreated and a test alert fired: `alertmanager_notifications_total{integration="telegram"} = 1`, all failure counters 0. (One test message reached the admin's Telegram.)
Note: the main bot token is reused for alerts; to separate them, create a second bot and change `ALERT_TELEGRAM_BOT_TOKEN`.

## 6. Actions for you
1. The one-time password and TOTP are in my chat reply and in `/root/melorin-credentials.txt` (mode 600); change the password after first login and delete the file.
2. **Copy `/opt/melorin/secrets/backup/age-identity.txt` off the server** (the only key that decrypts backups).
3. Open the bot once and press Start so Telegram can deliver messages.
4. **The GitHub token and the Telegram bot token were pasted in chat; revoke/rotate both** (bot: BotFather `/revoke`, then `melorin` menu → 3 → 1).
