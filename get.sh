#!/usr/bin/env bash
# Melorin one-line installer entry point.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/get.sh)
#
# What it does: checks root + apt, installs git/curl, fetches the project into
# /opt/melorin, registers the `melorin` command and opens the management menu
# (melorin.sh). Nothing is installed until you pick "1) Install" in the menu.
#
# Optional environment:
#   REPO_URL, APP_DIR
#   REPO_REF         branch, tag or commit. Default: the newest release tag (vX.Y.Z); `main` only while no tag exists.
#   REPO_COMMIT      full 40-char commit SHA the checkout must resolve to (supply-chain pin, T-W11). Recommended in production.
#   REPO_ALLOW_MAIN  set to 1 to knowingly install the moving `main` branch once releases exist.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/archerhabibi/melorin-py.git}"
REPO_REF="${REPO_REF:-}"
REPO_COMMIT="${REPO_COMMIT:-}"
REPO_ALLOW_MAIN="${REPO_ALLOW_MAIN:-0}"
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

# T-W11: never track the moving `main` branch by default. Prefer the newest vX.Y.Z tag; fall back to main only when the
# project has no release yet, and say so loudly.
if [ -z "$REPO_REF" ]; then
  REPO_REF="$(git tag --list 'v[0-9]*' --sort=-v:refname | head -n1)"
  if [ -z "$REPO_REF" ]; then
    REPO_REF="main"
    say "No release tag exists yet - installing the moving 'main' branch. Pin REPO_COMMIT for anything beyond a trial."
  else
    say "Installing release $REPO_REF"
  fi
elif [ "$REPO_REF" = "main" ] && [ "$REPO_ALLOW_MAIN" != "1" ] && [ -n "$(git tag --list 'v[0-9]*' | head -n1)" ]; then
  die "Refusing to install the moving 'main' branch while releases exist. Use a tag (REPO_REF=vX.Y.Z) or set REPO_ALLOW_MAIN=1."
fi
if git rev-parse --verify --quiet "origin/${REPO_REF}^{commit}" >/dev/null; then
  target="origin/${REPO_REF}"          # branch
else
  target="$REPO_REF"                   # tag or commit
fi
git -c advice.detachedHead=false checkout --quiet --detach "$target" \
  || die "Could not check out '$REPO_REF'. Local edits in $APP_DIR? Commit/stash them and retry."

if [ -n "$REPO_COMMIT" ]; then
  case "$REPO_COMMIT" in
    [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) ;;
    *) die "REPO_COMMIT must be a hexadecimal commit SHA." ;;
  esac
  actual="$(git rev-parse HEAD)"
  case "$actual" in
    "$REPO_COMMIT"*) say "Verified commit $actual" ;;
    *) die "Checked-out commit $actual does not match REPO_COMMIT $REPO_COMMIT. Aborting." ;;
  esac
fi

chmod +x melorin.sh scripts/*.sh 2>/dev/null || true
ln -sf "$APP_DIR/melorin.sh" /usr/local/bin/melorin
say "Command registered: run 'melorin' any time to open the menu."

export MELORIN_REPO_URL="$REPO_URL" MELORIN_REPO_REF="$REPO_REF"
exec bash "$APP_DIR/melorin.sh" "$@"
