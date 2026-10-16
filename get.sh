#!/usr/bin/env bash
# Melorin one-line installer entry point.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/get.sh)
#
# What it does: checks root + apt, installs git/curl, fetches the project into
# /opt/melorin, registers the `melorin` command and opens the management menu
# (melorin.sh). Nothing is installed until you pick "1) Install" in the menu.
#
# Optional environment: REPO_URL, REPO_REF (branch, tag or commit; default main), APP_DIR.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/archerhabibi/melorin-py.git}"
REPO_REF="${REPO_REF:-main}"
APP_DIR="${APP_DIR:-/opt/melorin}"

say() { printf '\033[1;36m>>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root (sudo -i), then run the command again."
command -v apt-get >/dev/null 2>&1 || die "This installer supports Ubuntu/Debian (apt) only."

need=()
command -v git  >/dev/null 2>&1 || need+=(git)
command -v curl >/dev/null 2>&1 || need+=(curl)
[ -e /etc/ssl/certs/ca-certificates.crt ] || need+=(ca-certificates)
if [ "${#need[@]}" -gt 0 ]; then
  say "Installing: ${need[*]}"
  apt-get update -y >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${need[@]}" >/dev/null
fi

if [ ! -d "$APP_DIR/.git" ]; then
  say "Downloading Melorin into $APP_DIR"
  mkdir -p "$(dirname "$APP_DIR")"
  git clone --quiet "$REPO_URL" "$APP_DIR"
else
  say "Updating the project files in $APP_DIR"
fi
cd "$APP_DIR"
git fetch --quiet --tags origin
if git rev-parse --verify --quiet "origin/${REPO_REF}^{commit}" >/dev/null; then
  target="origin/${REPO_REF}"          # branch
else
  target="$REPO_REF"                   # tag or commit
fi
git -c advice.detachedHead=false checkout --quiet --detach "$target" \
  || die "Could not check out '$REPO_REF'. Local edits in $APP_DIR? Commit/stash them and retry."

chmod +x melorin.sh scripts/*.sh 2>/dev/null || true
ln -sf "$APP_DIR/melorin.sh" /usr/local/bin/melorin
say "Command registered: run 'melorin' any time to open the menu."

export MELORIN_REPO_URL="$REPO_URL" MELORIN_REPO_REF="$REPO_REF"
exec bash "$APP_DIR/melorin.sh" "$@"
