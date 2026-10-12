#!/usr/bin/env bash
# Melorin server installer (Ubuntu/Debian). Run as root on the target server:
#   DOMAIN=shop.example.com ADMIN_DOMAIN=admin.example.com ADMIN_EMAIL=you@example.com \
#   bash scripts/install_server.sh
# Optional: MAIN_BOT_TOKEN (otherwise you are asked for it), REPO_URL, APP_DIR.
# Idempotent: an existing .env is never overwritten.
# Needs ports 80 and 443 free (Caddy obtains the TLS certificates automatically).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/archerhabibi/melorin-py.git}"
APP_DIR="${APP_DIR:-/opt/melorin}"
DOMAIN="${DOMAIN:?set DOMAIN, e.g. shop.example.com}"
ADMIN_DOMAIN="${ADMIN_DOMAIN:?set ADMIN_DOMAIN, e.g. admin.example.com}"
ADMIN_EMAIL="${ADMIN_EMAIL:?set ADMIN_EMAIL}"

# Only on a first install: the compose file publishes 80/443, so they must be free.
if [ ! -f "$APP_DIR/.env" ]; then
  for p in 80 443; do
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${p}\$"; then
      echo "Port ${p} is already in use on this server; free it before installing." >&2; exit 1
    fi
  done
fi

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
if ! command -v git >/dev/null 2>&1 || ! command -v openssl >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y git openssl
fi

if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
git pull --ff-only

rand() { openssl rand -hex 32; }
fernet() { head -c 32 /dev/urandom | base64 | tr '+/' '-_'; }

set_kv() { # set_kv KEY VALUE  (replace line or append)
  local k="$1" v="$2"
  if grep -qE "^${k}=" .env; then
    local esc="${v//\\/\\\\}"; esc="${esc//&/\\&}"; esc="${esc//|/\\|}"
    sed -i "s|^${k}=.*|${k}=${esc}|" .env
  else
    echo "${k}=${v}" >> .env
  fi
}

if [ ! -f .env ]; then
  # --- main Telegram bot token: the only bot configured at install time ---
  BOT="${MAIN_BOT_TOKEN:-}"
  if [ -z "$BOT" ] && [ -t 0 ]; then
    read -r -s -p "Main Telegram bot token (from @BotFather, Enter to skip): " BOT; echo
  fi
  if [ -n "$BOT" ] && ! [[ "$BOT" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]]; then
    echo "That does not look like a Telegram bot token; skipping it (add MELORIN_TELEGRAM_TOKEN to .env later)." >&2
    BOT=""
  fi

  cp .env.example .env
  PGPASS="$(rand)"
  set_kv MELORIN_ENV production
  set_kv POSTGRES_PASSWORD "$PGPASS"
  set_kv MELORIN_DATABASE_URL "postgresql+asyncpg://melorin:${PGPASS}@postgres:5432/melorin"
  set_kv MELORIN_JWT_SECRET "$(rand)"
  set_kv MELORIN_ENCRYPTION_KEY "$(fernet)"
  set_kv MELORIN_BOT_SERVICE_SECRET "$(rand)"
  set_kv MELORIN_METRICS_TOKEN "$(rand)"
  set_kv MELORIN_HEALTH_TOKEN "$(rand)"
  set_kv MELORIN_BOOTSTRAP_ADMIN_EMAIL "$ADMIN_EMAIL"
  set_kv MELORIN_BOOTSTRAP_ADMIN_PASSWORD "$(openssl rand -base64 24 | tr -d '/+=')"
  set_kv MELORIN_DOMAIN "$DOMAIN"
  set_kv MELORIN_ADMIN_DOMAIN "$ADMIN_DOMAIN"
  set_kv MELORIN_STORE_WEB_URL "https://${DOMAIN}"
  set_kv MELORIN_PUBLIC_API_URL "https://${DOMAIN}"
  set_kv MELORIN_CORS_ORIGINS "[\"https://${DOMAIN}\",\"https://${ADMIN_DOMAIN}\"]"
  set_kv MELORIN_SEED_DEMO_DATA false
  set_kv MELORIN_ALLOW_MOCK_PROVIDERS false
  if [ -n "$BOT" ]; then
    set_kv MELORIN_TELEGRAM_TOKEN "$BOT"
    set_kv MELORIN_MAIN_BOT_TOKEN "$BOT"
    # Soft check only (Telegram may be unreachable from some networks).
    if curl -fsS -m 10 "https://api.telegram.org/bot${BOT}/getMe" >/dev/null 2>&1; then
      echo ">> main bot token verified with Telegram."
    else
      echo ">> could not verify the bot token with Telegram (network or wrong token); continuing." >&2
    fi
  else
    echo ">> no bot token set: the main bot will not start until MELORIN_TELEGRAM_TOKEN is added to .env."
  fi
  chmod 600 .env
fi

# --- Local encrypted backups (no S3 / SMTP needed; both are optional and enabled later in the Admin panel) ---
# The worker only receives the PUBLIC age recipient. The private identity stays on the host in secrets/backup/.
mkdir -p secrets/backup
if [ ! -s secrets/backup/recipients.txt ]; then
  command -v age-keygen >/dev/null 2>&1 || { apt-get update -y && apt-get install -y age; }
  age-keygen -o secrets/backup/age-identity.txt >/dev/null 2>&1
  chmod 600 secrets/backup/age-identity.txt
  age-keygen -y secrets/backup/age-identity.txt > secrets/backup/recipients.txt
  chmod 644 secrets/backup/recipients.txt
  NEW_BACKUP_KEY=1
fi
chmod 755 secrets/backup
set_kv MELORIN_BACKUP_RECIPIENT_FILE /run/melorin-backup/recipients.txt

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && echo ">> ufw: opened 80/tcp and 443/tcp"
fi

docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d

echo
echo "Done."
echo "  Store : https://${DOMAIN}"
echo "  Admin : https://${ADMIN_DOMAIN}   (login: ${ADMIN_EMAIL})"
echo "  Admin password: ${APP_DIR}/.env -> MELORIN_BOOTSTRAP_ADMIN_PASSWORD (change it after first login)"
echo "  DNS   : both domains must point to this server (certificates are issued automatically on first visit)."
echo "  SMTP / S3: not required. Enable them later in Admin -> Settings -> Integrations."
echo "  Backups: encrypted, daily 02:00 UTC, stored locally in the api_storage volume (/app/var/backups)."
echo "  Reseller bots are disabled by default (compose profile 'reseller')."
if [ "${NEW_BACKUP_KEY:-0}" = 1 ]; then
  echo "  !! Copy ${APP_DIR}/secrets/backup/age-identity.txt to a safe place OFF this server."
  echo "     Without it the encrypted backups cannot be restored."
fi
