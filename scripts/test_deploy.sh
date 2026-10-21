#!/usr/bin/env bash
# Offline test for scripts/deploy.sh: a fake `docker` binary exercises success, backup failure, migration failure
# and post-deploy health failure (rollback). Needs only git + bash + flock; no Docker daemon.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=protocol.version GIT_CONFIG_VALUE_0=0
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

mkdir -p "$T/bin"
cat > "$T/bin/docker" <<'FAKE'
#!/usr/bin/env bash
# fake docker: behaviour driven by $FAKE_FAIL (backup|build|migrate|health) and the 'bad' marker in ./version.txt
[ "$1" = compose ] || exit 0
shift; while [ "${1:-}" = -f ]; do shift 2; done
echo "docker compose $*" >> "$APP_DIR/var/fake-docker.log"
case "$1" in
  build) [ "${FAKE_FAIL:-}" = build ] && exit 1; exit 0 ;;
  up) exit 0 ;;
  ps)
    case "$*" in
      *--services*) echo worker; exit 0 ;;
      *State*) echo "postgres running healthy"; echo "api running healthy"; echo "worker running healthy"; echo "telegram_main running unhealthy"; exit 0 ;;
      *) echo "api healthy"; echo "telegram_main unhealthy"; exit 0 ;;
    esac ;;
  run)
    case "$*" in
      *"alembic current"*) echo "0027_channel_binding (head)"; exit 0 ;;
      *"alembic upgrade"*) [ "${FAKE_FAIL:-}" = migrate ] && exit 1; exit 0 ;;
      *) exit 0 ;;
    esac ;;
  exec)
    case "$*" in
      *backup_secure*) [ "${FAKE_FAIL:-}" = backup ] && { echo "pg_dump: boom" >&2; exit 1; }; echo "/app/var/backups/melorin-TEST.dump.age"; exit 0 ;;
      *health/ready*) grep -q bad version.txt && exit 1; exit 0 ;;
    esac ;;
esac
exit 0
FAKE
chmod +x "$T/bin/docker"

new_env() { new_env_inner "$@" >/dev/null 2>&1; echo "$T/$1-srv"; }
new_env_inner() { # new_env <name> -> prepares origin + server clone, leaves server at commit 1, origin/main at commit 2 (bad when $2=bad)
  local n="$1" kind="${2:-good}"
  git init -q --bare -b main "$T/$n-origin.git"
  git clone -q "$T/$n-origin.git" "$T/$n-work" 2>/dev/null
  ( cd "$T/$n-work"
    mkdir -p scripts; cp "$SRC/scripts/deploy.sh" scripts/; printf '#!/usr/bin/env bash\nexit 0\n' > scripts/ops_log.sh; chmod +x scripts/*.sh
    echo good > version.txt; echo "services: {}" > docker-compose.yml; echo "ALERT_TELEGRAM_BOT_TOKEN=x" > .env.tracked-not
    printf 'var/\n.env\n' > .gitignore
    git add -A; git commit -qm one; git branch -M main; git push -q origin main
    echo "$kind-v2" > version.txt; git commit -qam two; git push -q origin main )
  git clone -q "$T/$n-origin.git" "$T/$n-srv" 2>/dev/null
  ( cd "$T/$n-srv"; git checkout -q --detach "$(git rev-parse HEAD~1)"; echo "ALERT_TELEGRAM_BOT_TOKEN=x" > .env; mkdir -p var )
}
run() { ( cd "$1"; shift; env PATH="$T/bin:$PATH" APP_DIR="$PWD" DEPLOY_HEALTH_TIMEOUT=6 "$@" bash scripts/deploy.sh 2>&1 ); }
fail() { echo "FAIL: $*"; exit 1; }
v() { cat "$1/version.txt"; }

# 1) success
S="$(new_env ok good)"; out="$(run "$S" FAKE_FAIL=none || true)"
git -C "$S" log -1 --format=%s | grep -q two || fail "success: not on commit two ($out)"
grep -q "deploy OK" <<<"$out" || fail "success: no OK line ($out)"
grep -q "melorin-TEST.dump.age" <<<"$out" || fail "success: backup path not reported"
grep -q "bot not healthy: telegram_main" <<<"$out" || fail "success: unhealthy bot should only warn"
echo "ok  1 success"

# 2) health failure -> rollback to commit one
S="$(new_env bad bad)"; set +e; out="$(run "$S" FAKE_FAIL=none)"; rc=$?; set -e
[ "$rc" = 1 ] || fail "health: expected exit 1, got $rc ($out)"
git -C "$S" log -1 --format=%s | grep -q one || fail "health: not rolled back ($out)"
grep -q "rollback complete" <<<"$out" || fail "health: no rollback line ($out)"
echo "ok  2 health failure rolls back"

# 3) migration failure -> rollback
S="$(new_env mig good)"; set +e; out="$(run "$S" FAKE_FAIL=migrate)"; rc=$?; set -e
[ "$rc" = 1 ] || fail "migrate: expected exit 1 ($rc)"
git -C "$S" log -1 --format=%s | grep -q one || fail "migrate: not rolled back"
echo "ok  3 migration failure rolls back"

# 4) backup failure -> abort before touching the checkout
S="$(new_env bk good)"; set +e; out="$(run "$S" FAKE_FAIL=backup)"; rc=$?; set -e
[ "$rc" = 1 ] || fail "backup: expected exit 1 ($rc)"
git -C "$S" log -1 --format=%s | grep -q one || fail "backup: checkout changed despite failed backup"
grep -q "deploy aborted" <<<"$out" || fail "backup: no abort message"
echo "ok  4 backup failure aborts"

# 5) hand-edited tracked file -> refuse
S="$(new_env dirty good)"; echo x >> "$S/version.txt"; set +e; out="$(run "$S" FAKE_FAIL=none)"; rc=$?; set -e
[ "$rc" = 1 ] && grep -q "edited by hand" <<<"$out" || fail "dirty tree not refused ($out)"
echo "ok  5 dirty tree refused"
echo "deploy.sh tests passed"
