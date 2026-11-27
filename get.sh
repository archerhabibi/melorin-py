#!/usr/bin/env bash
# Melorin one-line installer (bootstrap).
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/get.sh)
#
# What it does: elevates to root (sudo), checks the server (apt, network), installs git/curl/openssl, fetches the project
# into /opt/melorin, registers the `melorin` command and hands over to melorin.sh. Nothing is installed until you pick
# "1) Install" in the menu, or run an unattended install:
#
#   bash <(curl -fsSL .../get.sh) install --domain shop.example.com --admin-domain admin.example.com \
#        --email you@example.com --yes                       # bot token via MAIN_BOT_TOKEN or --bot-token-file
#   bash <(curl -fsSL .../get.sh) doctor                     # read-only server check, installs nothing
#   curl -fsSL .../get.sh | sudo bash -s -- install --yes ...   # the pipe form works too
#
# Options of get.sh itself (everything after them is passed to melorin.sh: menu | install | update | status | doctor ...):
#   --ref REF      branch, tag or commit.  Default: the newest release tag vX.Y.Z; `main` only while no tag exists.
#   --commit SHA   full 40-char commit SHA the checkout must resolve to (supply-chain pin, T-W11). Recommended in production.
#   --allow-main   knowingly install the moving `main` branch although releases exist.
#   --dir PATH     install location (default /opt/melorin).        --repo URL   git remote (default: the official repo).
#   --force        downgrade the hardware/OS checks (RAM, disk, OS version) from failures to warnings.
# The same settings exist as environment variables: REPO_REF, REPO_COMMIT, REPO_ALLOW_MAIN=1, APP_DIR, REPO_URL, MELORIN_FORCE=1.
#
# Everything lives in functions and the last statement calls main: a download cut short by the network defines functions
# and does nothing (a plain top-to-bottom script would run half of itself).
# shellcheck disable=SC1091  # /etc/os-release is sourced on purpose
set -Eeuo pipefail
umask 022

init_vars() {
  REPO_URL_EXPLICIT=""
  if [ -n "${REPO_URL:-}" ]; then REPO_URL_EXPLICIT=1; fi
  REPO_URL="${REPO_URL:-https://github.com/archerhabibi/melorin-py.git}"
  REPO_REF="${REPO_REF:-}"
  REPO_COMMIT="${REPO_COMMIT:-}"
  REPO_ALLOW_MAIN="${REPO_ALLOW_MAIN:-0}"
  APP_DIR="${APP_DIR:-/opt/melorin}"
  LOG_FILE="${MELORIN_LOG_FILE:-/var/log/melorin-install.log}"
  MELORIN_FORCE="${MELORIN_FORCE:-0}"
  LOG_READY=""
  CLEANUP_DIRS=()
  if [ -t 2 ]; then C_I=$'\033[1;36m'; C_W=$'\033[1;33m'; C_E=$'\033[1;31m'; C_0=$'\033[0m'; else C_I=""; C_W=""; C_E=""; C_0=""; fi
}

log()  { if [ -n "$LOG_READY" ]; then printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >>"$LOG_FILE"; fi; return 0; }
say()  { printf '%s>>%s %s\n' "$C_I" "$C_0" "$*"; log "$*"; }
warn() { printf '%s!!%s %s\n' "$C_W" "$C_0" "$*" >&2; log "WARN $*"; }
die()  { printf '%sXX%s %s\n' "$C_E" "$C_0" "$*" >&2; log "FATAL $*"; exit 1; }

usage() {
  cat <<'EOF'
Melorin installer
  bash <(curl -fsSL https://raw.githubusercontent.com/archerhabibi/melorin-py/main/get.sh) [get.sh options] [command [command options]]

Commands (handled by melorin.sh): menu (default) | install | update | status | doctor | restart | logs
  install --domain D --admin-domain A --email E [--admin-tg ID] [--bot-token-file F] [--external-proxy] [--skip-dns-check] --yes
  doctor                       read-only check of this server; installs nothing

get.sh options:
  --ref REF      branch, tag or commit (default: newest release tag vX.Y.Z; main only while no release exists)
  --commit SHA   full 40-char commit SHA the checkout must match (supply-chain pin)
  --allow-main   install the moving main branch although releases exist
  --dir PATH     install location (default /opt/melorin)
  --repo URL     git remote (default: the official repository)
  --force        downgrade RAM / disk / OS-version failures to warnings
Environment: REPO_REF REPO_COMMIT REPO_ALLOW_MAIN=1 APP_DIR REPO_URL MELORIN_FORCE=1 MAIN_BOT_TOKEN ADMIN_TELEGRAM_ID
EOF
}

on_err() { # on_err RC LINE
  trap - ERR
  printf '%sXX%s get.sh stopped unexpectedly (exit %s, line %s).\n' "$C_E" "$C_0" "$1" "$2" >&2
  if [ -n "$LOG_READY" ]; then printf '   Details: %s\n' "$LOG_FILE" >&2; fi
  printf '   It is safe to run the same command again.\n' >&2
}
on_exit() { local d; for d in "${CLEANUP_DIRS[@]}"; do rm -rf "$d"; done; }

# ---------------------------------------------------------------- small helpers (a copy of what scripts/lib/common.sh has)
retry() { # retry TRIES DELAY cmd...   (_r_* names: bash `local` is dynamically scoped, see scripts/lib/common.sh)
  local _r_tries="$1" _r_delay="$2" _r_n=1 _r_what; shift 2
  _r_what="$*"
  until "$@"; do
    if [ "$_r_n" -ge "$_r_tries" ]; then return 1; fi
    warn "attempt $_r_n/$_r_tries failed: ${_r_what:0:90} (retrying in ${_r_delay}s)"
    sleep "$_r_delay"; _r_n=$((_r_n + 1)); _r_delay=$((_r_delay * 2))
  done
}
apt_run() {
  DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l NEEDRESTART_SUSPEND=1 \
    apt-get -o DPkg::Lock::Timeout=300 -o Acquire::Retries=3 \
            -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "$@"
}

# ---------------------------------------------------------------- steps
parse_args() { # sets MELORIN_ARGS (what melorin.sh receives)
  while [ $# -gt 0 ]; do
    case "$1" in
      -h|--help) usage; exit 0 ;;
      --ref|--commit|--dir|--repo)
        [ $# -ge 2 ] || die "$1 needs a value (see --help)"
        set_opt "$1" "$2"; shift ;;
      --ref=*|--commit=*|--dir=*|--repo=*) set_opt "${1%%=*}" "${1#*=}" ;;
      --allow-main) REPO_ALLOW_MAIN=1 ;;
      --force) MELORIN_FORCE=1 ;;
      --) shift; break ;;
      -*) die "Unknown option '$1'. Options of get.sh come first; options of a melorin command (install --domain ...) come after the command. See --help." ;;
      *) break ;;
    esac
    shift
  done
  MELORIN_ARGS=("$@")
}
set_opt() {
  case "$1" in
    --ref) REPO_REF="$2" ;;
    --commit) REPO_COMMIT="$2" ;;
    --dir) APP_DIR="$2" ;;
    --repo) REPO_URL="$2"; REPO_URL_EXPLICIT=1 ;;
  esac
}

validate_inputs() {
  [[ "$APP_DIR" == /* ]] || die "--dir must be an absolute path (got '$APP_DIR')."
  case "$APP_DIR" in /|/usr|/bin|/sbin|/lib|/etc|/var|/root|/home|/boot|/dev|/proc|/sys|/tmp) die "Refusing to use '$APP_DIR' as the install directory." ;; esac
  if [ -n "$REPO_REF" ]; then
    [[ "$REPO_REF" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || die "Invalid ref '$REPO_REF' (letters, digits, . _ / - only)."
  fi
  if [ -n "$REPO_COMMIT" ]; then
    [[ "$REPO_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "REPO_COMMIT / --commit must be the full 40-character lowercase commit SHA (an abbreviated one is not a real pin)."
  fi
}

ensure_root() { # not root: run again through sudo (works for `bash <(curl ...)`, where the script has no file to re-read)
  [ "$(id -u)" -eq 0 ] && return 0
  [ -z "${_MELORIN_ELEVATED:-}" ] || die "Could not become root through sudo."
  command -v sudo >/dev/null 2>&1 || die "Run as root: open a root shell (sudo -i) or prefix the command with sudo, then run it again."
  say "Not root: continuing through sudo (it may ask for your password)"
  # shellcheck disable=SC2016  # the single quotes are deliberate: $@ must be expanded by the NEW shell
  exec sudo -E env _MELORIN_ELEVATED=1 bash -c "set -Eeuo pipefail; umask 022; $(declare -f); main \"\$@\"" melorin-get "${ORIG_ARGS[@]}"
}

init_log() {
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
  if ( umask 077; : >>"$LOG_FILE" ) 2>/dev/null; then
    chmod 600 "$LOG_FILE" 2>/dev/null || true
    LOG_READY=1
    log "=== get.sh start (ref='${REPO_REF:-auto}' dir=$APP_DIR args=${MELORIN_ARGS[*]:-menu})"
  else
    warn "Cannot write $LOG_FILE; continuing without a log file."
  fi
}

check_server() {
  command -v apt-get >/dev/null 2>&1 || die "This installer supports Ubuntu / Debian (apt) only."
  [ -r /etc/os-release ] || die "/etc/os-release is missing: cannot tell which Linux this is."
  local id id_like
  id="$(. /etc/os-release && printf '%s' "${ID:-}")"; id_like="$(. /etc/os-release && printf '%s' "${ID_LIKE:-}")"
  case "$id $id_like" in
    *ubuntu*|*debian*) ;;
    *) die "Unsupported distribution '$id'. Melorin installs on Ubuntu 22.04+ / Debian 12+." ;;
  esac
  case "$(dpkg --print-architecture 2>/dev/null || uname -m)" in
    amd64|arm64|x86_64|aarch64) ;;
    *) [ "$MELORIN_FORCE" = 1 ] || die "Unsupported CPU architecture (amd64 / arm64 only). --force to try anyway." ;;
  esac
}

check_network() { # curl exists here: the user just used it to fetch this script
  if ! getent hosts github.com >/dev/null 2>&1; then
    die "DNS lookup of github.com failed. Fix the resolver (/etc/resolv.conf, e.g. nameserver 1.1.1.1) and run the command again."
  fi
  retry 3 3 curl -fsS -m 15 -o /dev/null https://github.com 2>>"${LOG_FILE:-/dev/null}" \
    || die "Cannot reach https://github.com (firewall, proxy or a blocked route). Melorin cannot be downloaded from here."
}

install_prereqs() {
  local need=()
  command -v git     >/dev/null 2>&1 || need+=(git)
  command -v curl    >/dev/null 2>&1 || need+=(curl)
  command -v openssl >/dev/null 2>&1 || need+=(openssl)
  command -v ss      >/dev/null 2>&1 || need+=(iproute2)
  command -v flock   >/dev/null 2>&1 || need+=(util-linux)
  [ -e /etc/ssl/certs/ca-certificates.crt ] || need+=(ca-certificates)
  [ "${#need[@]}" -gt 0 ] || return 0
  say "Installing prerequisites: ${need[*]}"
  { retry 4 5 apt_run update -qq && retry 3 5 apt_run install -y -qq --no-install-recommends "${need[@]}"; } >>"$LOG_FILE" 2>&1 \
    || { tail -n 12 "$LOG_FILE" >&2; die "apt could not install ${need[*]} (output above, full log: $LOG_FILE). Check the network, DNS and /etc/apt/sources.list, then run again."; }
}

latest_release_tag() { # newest strict vX.Y.Z tag of the checkout in $1 (release candidates such as v1.0.0-rc1 are not releases)
  git -C "$1" tag --list 'v[0-9]*' | { grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' || true; } | sort -V | tail -n1
}

fetch_project() {
  local tmp
  if [ ! -d "$APP_DIR/.git" ]; then
    if [ -e "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
      die "$APP_DIR exists, is not empty and is not a Melorin git checkout (an earlier attempt may have failed). Copy what you need (.env, secrets/), remove it, or pick another place with --dir."
    fi
    say "Downloading Melorin into $APP_DIR"
    mkdir -p "$(dirname "$APP_DIR")"
    tmp="$(mktemp -d "${APP_DIR}.partial.XXXXXX")"; CLEANUP_DIRS+=("$tmp")
    # clone into a sub-directory that does not exist yet: a failed attempt then leaves nothing behind for the retry to trip over
    retry 4 5 git clone --quiet "$REPO_URL" "$tmp/src" >>"$LOG_FILE" 2>&1 \
      || die "git clone of $REPO_URL failed (see $LOG_FILE). Check that github.com is reachable, then run again."
    rmdir "$APP_DIR" 2>/dev/null || true
    mv "$tmp/src" "$APP_DIR"
  else
    say "Updating the project files in $APP_DIR"
    if [ -n "$REPO_URL_EXPLICIT" ]; then git -C "$APP_DIR" remote set-url origin "$REPO_URL"; fi
  fi
  # Permissions are managed by the installer (chmod below); without this git sees every changed mode bit as a local edit,
  # which blocks later updates and trips the drift recorder.
  git -C "$APP_DIR" config core.fileMode false
  git -C "$APP_DIR" config advice.detachedHead false
  retry 4 5 git -C "$APP_DIR" fetch --quiet --tags --prune origin >>"$LOG_FILE" 2>&1 \
    || die "git fetch failed (see $LOG_FILE). Check that github.com is reachable, then run again."
  if [ -n "$(git -C "$APP_DIR" status --porcelain --untracked-files=no)" ]; then
    git -C "$APP_DIR" status --short --untracked-files=no >&2
    die "$APP_DIR has local edits to tracked files (listed above). Server-side edits are not supported: keep them with 'git -C $APP_DIR stash' (or discard with 'git -C $APP_DIR checkout -- .') and run again."
  fi
}

checkout_target() {
  local latest target
  latest="$(latest_release_tag "$APP_DIR")"
  if [ -z "$REPO_REF" ]; then
    if [ -n "$latest" ]; then
      REPO_REF="$latest"; say "Installing release $REPO_REF"
    else
      REPO_REF=main; warn "No release tag exists yet: installing the moving 'main' branch. Use --commit <full sha> to pin anything beyond a trial."
    fi
  elif [ "$REPO_REF" = main ] && [ "$REPO_ALLOW_MAIN" != 1 ] && [ -n "$latest" ]; then
    die "Refusing to install the moving 'main' branch while releases exist (newest: $latest). Use --ref $latest or --allow-main."
  fi
  if   git -C "$APP_DIR" rev-parse --verify --quiet "refs/remotes/origin/${REPO_REF}^{commit}" >/dev/null; then target="refs/remotes/origin/${REPO_REF}"
  elif git -C "$APP_DIR" rev-parse --verify --quiet "refs/tags/${REPO_REF}^{commit}"            >/dev/null; then target="refs/tags/${REPO_REF}"
  elif git -C "$APP_DIR" rev-parse --verify --quiet "${REPO_REF}^{commit}"                      >/dev/null; then target="$REPO_REF"
  else die "Unknown ref '$REPO_REF': it is neither a branch, a tag nor a commit of $REPO_URL."
  fi
  git -C "$APP_DIR" checkout --quiet --detach "$target" >>"$LOG_FILE" 2>&1 \
    || die "Could not check out '$REPO_REF' in $APP_DIR (see $LOG_FILE)."
  if [ -n "$REPO_COMMIT" ]; then
    local actual; actual="$(git -C "$APP_DIR" rev-parse HEAD)"
    [ "$actual" = "$REPO_COMMIT" ] || die "Checked-out commit $actual does not match the pin $REPO_COMMIT. Aborting."
    say "Verified commit $actual"
  fi
}

finish_checkout() {
  chmod +x "$APP_DIR/melorin.sh" "$APP_DIR"/scripts/*.sh 2>/dev/null || true
  # A checkout made under umask 077 (hardened host) leaves bind-mounted config unreadable for the non-root containers
  # (alertmanager/prometheus run as 'nobody'). Re-apply readable perms on everything except secrets, .env and .git.
  ( cd "$APP_DIR" \
    && find . -path ./.git -prune -o -path ./secrets -prune -o -path ./.env -prune -o -type d -exec chmod go+rx {} + 2>/dev/null \
    && find . -path ./.git -prune -o -path ./secrets -prune -o -path ./.env -prune -o -type f -exec chmod go+r {} + 2>/dev/null ) || true
  ln -sf "$APP_DIR/melorin.sh" /usr/local/bin/melorin
  say "Command registered: run 'melorin' any time to open the menu."
}

main() {
  local ORIG_ARGS=("$@")
  init_vars
  MELORIN_ARGS=()
  parse_args "$@"
  validate_inputs
  ensure_root
  init_log
  trap 'on_err $? $LINENO' ERR
  trap on_exit EXIT
  check_server
  check_network
  install_prereqs
  fetch_project
  checkout_target
  finish_checkout

  export MELORIN_REPO_URL="$REPO_URL" MELORIN_REPO_REF="$REPO_REF" MELORIN_LOG_FILE="$LOG_FILE" MELORIN_FORCE
  trap - ERR EXIT
  on_exit
  exec bash "$APP_DIR/melorin.sh" "${MELORIN_ARGS[@]}"
}

# Run only when executed (also for `bash <(curl ...)` and `curl | bash`); `source get.sh` merely loads the functions (tests).
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then main "$@"; fi
