#!/usr/bin/env bash
# Make bind-mounted, NON-secret project files readable for containers that run as non-root users
# (alertmanager / prometheus run as "nobody"). Safe to run at any time; idempotent; never touches secrets.
#
# Why: on hosts hardened with `umask 077` (or after a manual `git clone` / `git checkout` under such a umask) the checkout
# is 0600/0700 and these containers crash-loop with "can't open ...: Permission denied". Setting `umask 022` only helps
# for files created by the installer itself, so every checkout step also calls this script.
set -euo pipefail
APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$APP_DIR"
for p in infra docker-compose.yml docker-compose.external.yml; do
  [ -e "$p" ] && chmod -R go+rX "$p"
done
# alertmanager runs `/bin/sh /etc/alertmanager/entrypoint.sh`: it must be readable, not executable by others.
[ -f infra/alertmanager-entrypoint.sh ] && chmod 755 infra/alertmanager-entrypoint.sh
# The public age recipient is the only file of secrets/backup that containers read.
[ -f secrets/backup/recipients.txt ] && chmod 644 secrets/backup/recipients.txt
exit 0
