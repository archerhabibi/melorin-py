#!/usr/bin/env bash
# Install the automatic recorder as a cron job. Run as root. Safe to re-run.
#   sudo bash scripts/install_ops_watch.sh [/opt/melorin]
set -euo pipefail
APP="$(cd "${1:-$(dirname "$0")/..}" && pwd)"
OWNER="$(stat -c %U "$APP")"
command -v cron >/dev/null 2>&1 || command -v crond >/dev/null 2>&1 || { apt-get update -y && apt-get install -y cron; }
systemctl enable --now cron >/dev/null 2>&1 || true
printf '*/5 * * * * %s cd %s && scripts/ops_watch.sh >/dev/null 2>&1\n' "$OWNER" "$APP" > /etc/cron.d/melorin-ops-watch
chmod 644 /etc/cron.d/melorin-ops-watch
# capture the baseline now (as the project owner, so file ownership stays consistent)
if [ "$(id -un)" = "$OWNER" ]; then
  (cd "$APP" && scripts/ops_watch.sh) || true
else
  runuser -u "$OWNER" -- bash -c "cd '$APP' && scripts/ops_watch.sh" 2>/dev/null \
    || sudo -u "$OWNER" bash -c "cd '$APP' && scripts/ops_watch.sh" || true
fi
echo "ops-watch installed: every 5 min as '$OWNER' -> $APP/var/ops-log.md"
