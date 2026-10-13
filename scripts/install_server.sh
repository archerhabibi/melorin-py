#!/usr/bin/env bash
# Melorin server installer (Ubuntu/Debian). Run as root on the target server:
#   DOMAIN=shop.example.com ADMIN_DOMAIN=admin.example.com ADMIN_EMAIL=you@example.com \
#   bash scripts/install_server.sh
# Optional: MAIN_BOT_TOKEN (otherwise you are asked for it), REPO_URL, REPO_REF, APP_DIR,
# EXTERNAL_PROXY=true when ports 80/443 are already owned by a host proxy.
# Idempotent: an existing .env is never overwritten. New environments are
# assembled in .env.tmp and atomically renamed only after validation succeeds.
# Default mode uses the bundled Caddy. EXTERNAL_PROXY=true uses loopback
# bindings and leaves TLS/routing to the existing host proxy.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/archerhabibi/melorin-py.git}"
# Pin production installs to a reviewed commit; override only during a deliberate release.
REPO_REF="${REPO_REF:-9d8d4e0}"
APP_DIR="${APP_DIR:-/opt/melorin}"
DOMAIN="${DOMAIN:?set DOMAIN, e.g. shop.example.com}"
ADMIN_DOMAIN="${ADMIN_DOMAIN:?set ADMIN_DOMAIN, e.g. admin.example.com}"
ADMIN_EMAIL="${ADMIN_EMAIL:?set ADMIN_EMAIL}"
EXTERNAL_PROXY="${EXTERNAL_PROXY:-false}"

compose_files=(-f docker-compose.yml)
if [ "$EXTERNAL_PROXY" = "true" ]; then
  compose_files+=(-f docker-compose.external.yml)
else
  export COMPOSE_PROFILES="${COMPOSE_PROFILES:-local-proxy}"
fi
compose() { docker compose "${compose_files[@]}" "$@"; }

# Only bundled-proxy installs require public ports to be free.
if [ "$EXTERNAL_PROXY" != "true" ] && [ ! -f "$APP_DIR/.env" ]; then
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
# Never deploy an unreviewed moving branch. Fetch and check out the pinned release.
git fetch --quiet --tags origin main
git checkout --quiet --detach "$REPO_REF"

rand() { openssl rand -hex 32; }
fernet() { head -c 32 /dev/urandom | base64 | tr '+/' '-_'; }

set_kv() { # set_kv KEY VALUE  (replace line or append)
  local k="$1" v="$2" file="${ENV_FILE:-.env}"
  if grep -qE "^${k}=" "$file"; then
    local esc="${v//\\/\\\\}"; esc="${esc//&/\\&}"; esc="${esc//|/\\|}"
    sed -i "s|^${k}=.*|${k}=${esc}|" "$file"
  else
    echo "${k}=${v}" >> "$file"
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

  # Never expose a half-written production environment to Compose or a retry.
  ENV_FILE=.env.tmp
  export ENV_FILE
  rm -f "$ENV_FILE"
  cp .env.example "$ENV_FILE"
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
  # RFC 6238 secrets must be RFC 4648 base32, not hexadecimal text.
  # 20 random bytes = 160 bits = exactly 32 base32 characters (no padding, no filler).
  BOOTSTRAP_TOTP="$(head -c 20 /dev/urandom | base32 | tr -d '=\n')"
  set_kv MELORIN_BOOTSTRAP_ADMIN_TOTP_SECRET "$BOOTSTRAP_TOTP"
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
  unset BOT
  mv -f "$ENV_FILE" .env
  unset ENV_FILE
  chmod 600 .env
fi
# --- Local encrypted backups (S3 / SMTP are optional and enabled later in Admin) ---
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
# Optional bootstrap value for operators who already have an off-site target.
# It is intentionally not required: S3/rclone can be configured later in Admin.
if [ -n "${BACKUP_OFFSITE_URI:-}" ]; then
  set_kv MELORIN_BACKUP_OFFSITE_URI "$BACKUP_OFFSITE_URI"
fi

# Prometheus reads a file secret, not the .env value. Write it atomically and
# keep it readable only by the monitoring container's root user.
mkdir -p secrets
tmp_metrics="$(mktemp secrets/.metrics-token.XXXXXX)"
printf '%s\n' "$(sed -n 's/^MELORIN_METRICS_TOKEN=//p' .env)" > "$tmp_metrics"
chmod 600 "$tmp_metrics"
mv -f "$tmp_metrics" secrets/metrics-token

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && echo ">> ufw: opened 80/tcp and 443/tcp"
fi

compose build
compose run --rm api alembic upgrade head
# Capture the one-time password before bootstrap, then remove it from disk.
BOOTSTRAP_PASSWORD="$(sed -n 's/^MELORIN_BOOTSTRAP_ADMIN_PASSWORD=//p' .env)"
compose up -d
# Migrations do not create the first operator account. Bootstrap is explicit,
# idempotent, and runs only after the database and application image exist.
compose run --rm api python -m melorin.cli bootstrap
# The one-time bootstrap TOTP is persisted encrypted in the database; do not
# leave the raw seed in the long-lived environment file.
if grep -q '^MELORIN_BOOTSTRAP_ADMIN_PASSWORD=' .env; then
  sed -i '/^MELORIN_BOOTSTRAP_ADMIN_PASSWORD=/d' .env
  chmod 600 .env
fi
if grep -q '^MELORIN_BOOTSTRAP_ADMIN_TOTP_SECRET=' .env; then
  BOOTSTRAP_TOTP="$(sed -n 's/^MELORIN_BOOTSTRAP_ADMIN_TOTP_SECRET=//p' .env)"
  sed -i '/^MELORIN_BOOTSTRAP_ADMIN_TOTP_SECRET=/d' .env
  chmod 600 .env
fi
bash scripts/install_ops_watch.sh "$APP_DIR" || echo ">> could not install the automatic change recorder (see scripts/install_ops_watch.sh)" >&2

echo
echo "Done."
echo "  Store : https://${DOMAIN}"
echo "  Admin : https://${ADMIN_DOMAIN}   (login: ${ADMIN_EMAIL})"
if [ -n "${BOOTSTRAP_PASSWORD:-}" ]; then
  echo "  Admin password (save now, then it is removed from .env): ${BOOTSTRAP_PASSWORD}"
fi
if [ -n "${BOOTSTRAP_TOTP:-}" ]; then
  echo "  Admin TOTP secret (save once in an authenticator): ${BOOTSTRAP_TOTP}"
fi
echo "  DNS   : both domains must point to this server (certificates are issued automatically on first visit)."
if [ "$EXTERNAL_PROXY" = "true" ]; then
  echo "  Proxy : external mode; route the host proxy to 127.0.0.1:18080 (store) and 127.0.0.1:18081 (admin)."
  echo "          Route /api/* and /health/* to 127.0.0.1:18000."
fi
echo "  SMTP / S3: not required. Enable them later in Admin -> Settings -> Integrations."
echo "  Backups: encrypted, daily 02:00 UTC, stored locally in the api_storage volume (/app/var/backups)."
echo "  Server log: changes made on this server are recorded automatically in ${APP_DIR}/var/ops-log.md (add reasons with scripts/ops_log.sh)."
echo "  Reseller bots are disabled by default (compose profile 'reseller')."
if [ "${NEW_BACKUP_KEY:-0}" = 1 ]; then
  echo "  !! Copy ${APP_DIR}/secrets/backup/age-identity.txt to a safe place OFF this server."
  echo "     Without it the encrypted backups cannot be restored."
fi
