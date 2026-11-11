# T08 — What to fetch at install time vs. what to import after install (English)

## 1. Fetched automatically at install time (observed in the real run)
| Category | What | Notes / risk |
|---|---|---|
| OS packages | `git`, `curl`, `openssl`, `age`, `ufw`, `fail2ban` | Ubuntu archive; low risk |
| Docker | Docker CE 29.x from `get.docker.com` | script is run unpinned; the only "trust the latest" link in the chain |
| Base images | postgres:16, redis:7, caddy:2, prometheus 2.55.1, alertmanager 0.27.0, node:22, nginx:1.27, python:3.12 | **all pinned by digest** (good); about 1.8 GB |
| Build deps | pip (hash-locked), npm, PGDG key | built on the host (about 4 minutes) |
| TLS certificates | Let's Encrypt via Caddy | needs correct DNS and free ports 80/443 |
| Check | `getMe` call to Telegram | token validation only |

**Verdict:** the download set is correct and low-risk. Only suggestion: install Docker from the official apt repository with a pinned version instead of `get.docker.com`, and (if reachability from Iran is a concern) a local registry/mirror for the images (`MELORIN_IMAGE_REGISTRY` already exists in compose).

## 2. Ask only these five things at install time (current behaviour is right)
Store domain, admin domain, admin e-mail, bot token, admin numeric ID. Asking for more makes the install fragile and spreads secrets into `.env`. So VPN-panel data, payment gateways, SMTP, S3 etc. should **not** be collected at install; the README already keeps them runtime-configured and encrypted in the database.

## 3. Import after install (Admin panel → Settings / relevant sections) — suggested order
1. **First login:** TOTP in an authenticator app, change the password, delete `/root/melorin-credentials.txt`.
2. **Backups:** copy `age-identity.txt` off the server; then (optional) S3 for off-site copies (*Settings → Integrations*).
3. **VPN panels** (Sanaei / PasarGuard) and a connection test; only the panel URL and credentials (Melorin is only a mediator).
4. **Payment methods:** card-to-card and Zarinpal (wallet top-up only).
5. **Catalog:** sales bundles, prices, coupons.
6. **Login and mail:** SMTP (without it e-mail-code login is unavailable), Google and Telegram login if needed.
7. **Resellers:** domain + bot token in *Admin → Resellers* (no restart).
8. **Alerts:** press Start on the bot; optionally a separate alert bot.

## 4. Change in this branch (`chore/install-tuning-t06`)
- `docker-compose.yml`: **log rotation** for all 12 services (`json-file`, 10 MB × 3 files). Previously logs were never rotated and could fill the 38 GB disk over months.
- Validation: `docker compose config` valid, CI guard (`check_ops_p0.py`) green.
- (Applied on the live server and containers recreated; result at the end of this document.)

## 5. Suggestions deliberately not implemented (need your decision)
| Suggestion | Why not done |
|---|---|
| ACME e-mail for Caddy (`email` in the Caddyfile from the admin e-mail) | an empty value breaks the Caddyfile; needs a default and an update-path change |
| Pin Docker from the apt repo | changes install behaviour; better as a separate PR tested on Ubuntu 22.04/24.04 |
| `docker builder prune` after install | frees 1.6 GB but slows `melorin update`; unnecessary with 28 GB free |
| `net.core.rmem_max` for HTTP/3 | cosmetic warning only |
| Menu-less install (CI/automation) | already possible: `DOMAIN=… ADMIN_DOMAIN=… ADMIN_EMAIL=… MAIN_BOT_TOKEN=… ADMIN_TELEGRAM_ID=… SKIP_BOT_PROMPT=1 bash scripts/install_server.sh` |
