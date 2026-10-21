#!/usr/bin/env bash
# Melorin production deploy with automatic rollback (audit P0: W1/W3).
#
#   scripts/deploy.sh [--ref <git-ref>] [--skip-backup] [--db-downgrade]
#
# Steps (any failure after step 3 triggers an automatic rollback to the previous commit):
#   1. lock           one deploy at a time (flock on var/deploy.lock)
#   2. fetch/checkout the requested ref (default origin/main) as a detached HEAD; remember the previous commit
#   3. backup         encrypted pre-deploy DB backup through the running worker (scripts/backup_secure.sh); aborts if it fails
#   4. build          docker compose build
#   5. migrate        alembic upgrade head (Postgres DDL is transactional: a failed migration leaves the schema untouched)
#   6. up             docker compose up -d --remove-orphans
#   7. verify         wait for /health/ready (DB + Redis + worker heartbeat) and for every service to be healthy
#   8. rollback       on failure: checkout previous commit, rebuild, up -d, verify again, exit 1
#
# Database note: rollback restores the previous CODE. The schema stays at the new revision unless --db-downgrade is given
# (migrations 0002/0011/0023/0026 have no-op downgrades, so downgrade is opt-in). The pre-deploy backup path is printed
# on every failure so the data can be restored by hand if a migration was destructive.
#
# Environment: APP_DIR (default: repo root of this script), DEPLOY_HEALTH_TIMEOUT (default 180s), DEPLOY_SKIP_BACKUP=1,
# DEPLOY_REMOTE (default origin). Compose file selection mirrors melorin.sh (external proxy / local-proxy profile).
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
REMOTE="${DEPLOY_REMOTE:-origin}"
HEALTH_TIMEOUT="${DEPLOY_HEALTH_TIMEOUT:-180}"
REF=""
SKIP_BACKUP="${DEPLOY_SKIP_BACKUP:-0}"
DB_DOWNGRADE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF="${2:?--ref needs a value}"; shift 2 ;;
    --skip-backup) SKIP_BACKUP=1; shift ;;
    --db-downgrade) DB_DOWNGRADE=1; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

cd "$APP_DIR"
mkdir -p var
LOG_PREFIX="[deploy $(date -u +%H:%M:%S)]"
say()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s WARNING: %s\n' "$LOG_PREFIX" "$*" >&2; }
fail() { printf '%s ERROR: %s\n' "$LOG_PREFIX" "$*" >&2; }

env_get() { [ -f .env ] && sed -n "s/^$1=//p" .env | tail -n1 || true; }

compose() {
  local files=(-f docker-compose.yml) prof ext="false"
  prof="$(env_get COMPOSE_PROFILES)"
  if [ -f var/install-mode ]; then
    ext="$(sed -n 's/^EXTERNAL_PROXY=//p' var/install-mode | tail -n1)"; ext="${ext:-false}"
  fi
  if [ "$ext" = "true" ]; then
    files+=(-f docker-compose.external.yml)
  elif [[ ",${prof}," != *",local-proxy,"* ]]; then
    prof="${prof:+${prof},}local-proxy"
  fi
  [ -n "$prof" ] && export COMPOSE_PROFILES="$prof"
  # </dev/null: when this script is streamed through `ssh ... bash -s`, a docker command reading stdin would swallow the rest of it
  docker compose "${files[@]}" "$@" </dev/null
}

ops_log() { # ops_log <result> <ref> <note>
  [ -x scripts/ops_log.sh ] || return 0
  scripts/ops_log.sh -w "${SUDO_USER:-${USER:-deploy}}" -a deploy -b "previous: ${PREV_SHORT:-?}" -p "${3:--}" \
    -c "scripts/deploy.sh ${REF:-origin/main}" -r "$1" -f "$2" >/dev/null 2>&1 || true
}

# Wait until the API reports ready (DB + Redis + worker) and no service is unhealthy/restarting.
wait_healthy() {
  local deadline=$(( $(date +%s) + HEALTH_TIMEOUT )) ready=0 bad
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if compose exec -T api python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=4)' >/dev/null 2>&1; then
      ready=1
    else
      ready=0
    fi
    if [ "$ready" = 1 ]; then
      # Core services must be healthy. Bots are reported but never block: an install without a Telegram token has unhealthy bots by design.
      bad="$(compose ps --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null | awk -v core=" postgres redis api worker store_web admin_web caddy alertmanager prometheus " 'index(core, " "$1" ") && ($2=="restarting" || $2=="exited" || $2=="dead" || $3=="unhealthy" || $3=="starting") {print $1":"$2"/"$3}' | tr '\n' ' ')"
      if [ -z "$bad" ]; then
        compose ps --format '{{.Service}} {{.Health}}' 2>/dev/null | awk '$1 ~ /^telegram_/ && $2=="unhealthy" {print "bot not healthy: "$1}' | while read -r l; do warn "$l"; done
        return 0
      fi
      LAST_BAD="$bad"
    fi
    sleep 5
  done
  fail "health check failed after ${HEALTH_TIMEOUT}s (api ready=$ready${LAST_BAD:+, not healthy: $LAST_BAD})"
  return 1
}
LAST_BAD=""

# ------------------------------------------------------------------ 1) lock
exec 9>var/deploy.lock
if ! flock -n 9; then fail "another deploy is running (var/deploy.lock)"; exit 1; fi

# ------------------------------------------------------------------ 2) ref
[ -f .env ] || { fail ".env is missing; run the installer first"; exit 1; }
PREV="$(git rev-parse HEAD)"; PREV_SHORT="$(git rev-parse --short HEAD)"
say "fetching $REMOTE"
git fetch --quiet --tags "$REMOTE"
TARGET_REF="${REF:-$REMOTE/main}"
git rev-parse --verify --quiet "${TARGET_REF}^{commit}" >/dev/null || { fail "unknown ref: $TARGET_REF"; exit 1; }
TARGET="$(git rev-parse "${TARGET_REF}^{commit}")"; TARGET_SHORT="$(git rev-parse --short "$TARGET")"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  fail "tracked files were edited by hand on the server; refusing to deploy (git status)"; exit 1
fi
say "deploying $PREV_SHORT -> $TARGET_SHORT ($TARGET_REF)"

# Alerts that nobody receives are a silent failure; warn loudly (does not block).
if [ -z "$(env_get ALERT_TELEGRAM_BOT_TOKEN)" ] && [ -z "$(env_get ALERT_SMTP_HOST)" ]; then
  warn "no alert receiver configured in .env (ALERT_TELEGRAM_* / ALERT_SMTP_*): alerts will not be delivered"
fi

# ------------------------------------------------------------------ 3) backup
BACKUP_PATH="(none)"
if [ "$SKIP_BACKUP" = 1 ]; then
  warn "pre-deploy backup skipped on request"
elif compose ps --status running --services 2>/dev/null | grep -qx worker; then
  say "pre-deploy backup"
  if out="$(compose exec -T worker /app/scripts/backup_secure.sh 2>&1)"; then
    BACKUP_PATH="$(printf '%s\n' "$out" | tail -n1)"; say "backup: $BACKUP_PATH"
  elif [ "$?" = 3 ]; then
    BACKUP_PATH="$(printf '%s\n' "$out" | grep -E '\.age$' | tail -n1 || true)"; warn "local backup OK, off-site copy failed: $BACKUP_PATH"
  else
    fail "pre-deploy backup failed; deploy aborted (use --skip-backup to override)"; printf '%s\n' "$out" >&2
    ops_log "aborted (backup failed)" "$TARGET_SHORT" "pre-deploy backup failed"; exit 1
  fi
else
  warn "worker is not running (first install?); no pre-deploy backup taken"
fi

PREV_REV="$(compose run --rm -T api alembic current 2>/dev/null | awk '/^[0-9a-zA-Z_]+/ {print $1; exit}' || true)"

# ------------------------------------------------------------------ rollback
rollback() {
  local why="$1"
  fail "$why"
  say "ROLLBACK: restoring $PREV_SHORT"
  if [ "$DB_DOWNGRADE" = 1 ] && [ -n "$PREV_REV" ]; then
    say "downgrading database to $PREV_REV (requested with --db-downgrade)"
    compose run --rm -T api alembic downgrade "$PREV_REV" || warn "database downgrade failed; schema stays at the new revision"
  fi
  git -c advice.detachedHead=false checkout --quiet --detach "$PREV"
  if compose build && compose up -d --remove-orphans && wait_healthy; then
    say "rollback complete: serving $PREV_SHORT again"
    ops_log "rolled back to $PREV_SHORT" "$TARGET_SHORT" "$why"
  else
    fail "ROLLBACK ALSO FAILED - manual intervention required (previous commit $PREV, backup $BACKUP_PATH)"
    ops_log "ROLLBACK FAILED" "$TARGET_SHORT" "$why"
    exit 2
  fi
  fail "deploy of $TARGET_SHORT failed and was rolled back. Pre-deploy backup: $BACKUP_PATH"
  exit 1
}

git -c advice.detachedHead=false checkout --quiet --detach "$TARGET"

# ------------------------------------------------------------------ 4-6) build, migrate, up
say "building images"
compose build || rollback "image build failed"
say "running migrations"
compose run --rm -T api alembic upgrade head || rollback "migration failed (schema untouched: Postgres DDL is transactional)"
say "starting services"
compose up -d --remove-orphans || rollback "could not start services"

# ------------------------------------------------------------------ 7) verify
say "waiting for health (timeout ${HEALTH_TIMEOUT}s)"
wait_healthy || rollback "post-deploy health check failed"

docker image prune -f >/dev/null 2>&1 || true
ops_log "success" "$TARGET_SHORT" "git checkout, backup, build, migrate, up -d, health ok"
say "deploy OK: $TARGET_SHORT (previous $PREV_SHORT, backup $BACKUP_PATH)"
