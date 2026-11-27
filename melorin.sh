#!/usr/bin/env bash
# Melorin management menu.   Open it with:  melorin   (or: bash melorin.sh)
#
#   1) Install    quiet install -> asks only: store domain, admin domain, admin e-mail, bot token, admin Telegram ID
#   2) Update     pull latest code, rebuild, migrate, restart (.env is kept)
#   3) Edit .env  bot token / domains / open the file in an editor
#   4) Web panel  URLs, health check, admin password reset
#   5) Service    status / start / stop / restart / logs
#   6) Status     health summary
#   7) Uninstall  full removal
#   0) Exit
#
# Shortcuts:  melorin install|update|status|doctor|restart|logs|panel|help
#
# Unattended install (no questions; for automation, ssh without a terminal, cloud-init):
#   melorin install --domain shop.example.com --admin-domain admin.example.com --email you@example.com --yes
#   bot token: MAIN_BOT_TOKEN=... in the environment, or --bot-token-file FILE (never on the command line: it would sit in
#   `ps` and the shell history).  Also: --admin-tg ID  --store-name NAME  --external-proxy  --skip-dns-check  --force.  Environment equivalents:
#   DOMAIN ADMIN_DOMAIN ADMIN_EMAIL ADMIN_TELEGRAM_ID MAIN_STORE_NAME EXTERNAL_PROXY.
#   The install itself runs detached (own session, log in /var/log/melorin-install.log): an SSH drop cannot kill it halfway.
# Deliberately WITHOUT -e (unlike get.sh): the interactive menu must survive a failed action and return to the prompt; every
# step that matters checks its own status (`|| { err ...; return 1; }`). Audit V-036.
set -uo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
APP_DIR="$(cd "$(dirname "$SELF")" && pwd)"
# Must be a Melorin checkout. `melorin` has to be a SYMLINK to melorin.sh: a COPY would resolve APP_DIR to its own folder
# (e.g. /usr/local/bin) and "uninstall" would delete that.
if [ ! -f "$APP_DIR/docker-compose.yml" ] || [ ! -f "$APP_DIR/scripts/install_server.sh" ] || [ ! -f "$APP_DIR/scripts/lib/common.sh" ]; then
  echo "melorin.sh must run from inside a Melorin checkout (looked in $APP_DIR). If this is a copy, delete it and run: ln -sf /opt/melorin/melorin.sh /usr/local/bin/melorin" >&2
  exit 1
fi
# shellcheck source=scripts/lib/common.sh
. "$APP_DIR/scripts/lib/common.sh"
REPO_URL="${MELORIN_REPO_URL:-https://github.com/archerhabibi/melorin-py.git}"
LINK="/usr/local/bin/melorin"
trap ':' INT   # Ctrl-C stops a running child (e.g. logs) but keeps the menu alive

# Prompts need a terminal. Started through a pipe (curl | bash) answers come from the real terminal; with none at all (ssh
# without -t, cron, cloud-init) there is nobody to ask: has_tty really opens /dev/tty (the file exists even then, and a failed
# `exec </dev/tty` used to kill this script with a cryptic message and exit code 0).
HAVE_TTY=0
if [ -t 0 ]; then HAVE_TTY=1; elif has_tty; then exec </dev/tty; HAVE_TTY=1; fi
NONINTERACTIVE="${MELORIN_NONINTERACTIVE:-0}"; [ "$HAVE_TTY" = 1 ] || NONINTERACTIVE=1
# Inputs of an unattended install: the environment first, flags (parse_install_args) override.
OPT_DOMAIN="${DOMAIN:-}"; OPT_ADMIN_DOMAIN="${ADMIN_DOMAIN:-}"; OPT_EMAIL="${ADMIN_EMAIL:-}"; OPT_TG="${ADMIN_TELEGRAM_ID:-}"; OPT_STORE_NAME="${MAIN_STORE_NAME:-}"
OPT_TOKEN_FILE=""; OPT_SKIP_DNS=0; OPT_EXT="${EXTERNAL_PROXY:-}"; ASSUME_YES=0

C0=$'\033[0m'; CB=$'\033[1m'; CG=$'\033[1;32m'; CR=$'\033[1;31m'; CY=$'\033[1;33m'; CC=$'\033[1;36m'
info() { printf '%s>>%s %s\n' "$CC" "$C0" "$*"; }
ok()   { printf '%s OK%s %s\n' "$CG" "$C0" "$*"; }
warn() { printf '%s !!%s %s\n' "$CY" "$C0" "$*" >&2; }
err()  { printf '%s XX%s %s\n' "$CR" "$C0" "$*" >&2; }
pause() { read -r -p "Press Enter to continue..." _ || true; }

[ "$(id -u)" -eq 0 ] || { err "Run as root: sudo melorin"; exit 1; }
cd "$APP_DIR" || exit 1

# ---------------------------------------------------------------- helpers
ENV_FILE_PATH="$APP_DIR/.env"
installed() { [ -f "$ENV_FILE_PATH" ]; }

env_get() { [ -f "$ENV_FILE_PATH" ] && sed -n "s/^$1=//p" "$ENV_FILE_PATH" | tail -n1; }
env_set() { # env_set KEY VALUE
  local k="$1" v="$2" esc
  if grep -qE "^${k}=" "$ENV_FILE_PATH"; then
    esc="${v//\\/\\\\}"; esc="${esc//&/\\&}"; esc="${esc//|/\\|}"
    sed -i "s|^${k}=.*|${k}=${esc}|" "$ENV_FILE_PATH"
  else
    printf '%s=%s\n' "$k" "$v" >> "$ENV_FILE_PATH"
  fi
  chmod 600 "$ENV_FILE_PATH"
}

EXTERNAL_PROXY=false
REPO_REF="${MELORIN_REPO_REF:-main}"
load_mode() {
  local f="$APP_DIR/var/install-mode" v
  if [ -f "$f" ]; then
    v="$(sed -n 's/^EXTERNAL_PROXY=//p' "$f" | tail -n1)"; [ -n "$v" ] && EXTERNAL_PROXY="$v"
    v="$(sed -n 's/^REPO_REF=//p' "$f" | tail -n1)"; [ -n "$v" ] && [ -z "${MELORIN_REPO_REF:-}" ] && REPO_REF="$v"
  fi
}
load_mode

compose() {
  (
    cd "$APP_DIR" || exit 1
    local files=(-f docker-compose.yml) prof
    prof="$(env_get COMPOSE_PROFILES)"
    if [ "$EXTERNAL_PROXY" = "true" ]; then
      files+=(-f docker-compose.external.yml)
    elif [[ ",${prof}," != *",local-proxy,"* ]]; then
      prof="${prof:+${prof},}local-proxy"
    fi
    [ -n "$prof" ] && export COMPOSE_PROFILES="$prof"
    docker compose "${files[@]}" "$@"
  )
}

confirm() { # confirm "question" [default y|n]
  local def="${2:-n}" a hint="y/N"; [ "$def" = y ] && hint="Y/n"
  read -r -p "$1 [$hint] " a || a=""
  a="${a:-$def}"; [[ "$a" =~ ^[Yy] ]]
}

# norm_domain / valid_domain / valid_token / valid_email / server_ip / domain_ip / port_busy live in scripts/lib/common.sh

ask_domain() { # ask_domain "label" -> sets REPLY_DOMAIN
  local raw
  while true; do
    read -r -p "$1: " raw || return 1
    REPLY_DOMAIN="$(norm_domain "$raw")"
    valid_domain "$REPLY_DOMAIN" && return 0
    warn "Not a valid domain (example: shop.example.com)."
  done
}

ask_email() { # sets REPLY_EMAIL
  local e
  while true; do
    read -r -p "$1: " e || return 1
    e="${e,,}"; e="${e// /}"
    if valid_email "$e"; then REPLY_EMAIL="$e"; return 0; fi
    warn "Not a usable e-mail address (.test/.local/.invalid/.onion domains are refused by the app's login validator)."
  done
}

ask_token() { # sets REPLY_TOKEN (may be empty = skipped)
  local t
  while true; do
    read -r -s -p "4) Telegram bot token from @BotFather (hidden, Enter to skip): " t || t=""; echo
    t="${t// /}"
    if [ -z "$t" ]; then REPLY_TOKEN=""; return 0; fi
    if valid_token "$t"; then REPLY_TOKEN="$t"; return 0; fi
    warn "That does not look like a bot token (format 123456789:AA...)."
  done
}

ask_store_name() { # sets REPLY_STORE_NAME (may be empty = the neutral default; install_server.sh cleans it)
  read -r -p "${1:-6)} Store name as customers will see it (Enter for the default; changeable later in the admin panel): " REPLY_STORE_NAME || REPLY_STORE_NAME=""
}

valid_tg_id() { [[ "$1" =~ ^[1-9][0-9]{4,14}$ ]]; }
fold_digits() { printf '%s' "$1" | sed 's/۰/0/g;s/۱/1/g;s/۲/2/g;s/۳/3/g;s/۴/4/g;s/۵/5/g;s/۶/6/g;s/۷/7/g;s/۸/8/g;s/۹/9/g;s/٠/0/g;s/١/1/g;s/٢/2/g;s/٣/3/g;s/٤/4/g;s/٥/5/g;s/٦/6/g;s/٧/7/g;s/٨/8/g;s/٩/9/g' | tr -d '[:space:]'; }
ask_admin_tg() { # sets REPLY_TG (may be empty = skipped). $1 = prompt number/label
  local t
  while true; do
    read -r -p "${1:-5)} Numeric Telegram ID of the main admin (get it from @userinfobot; Enter to skip): " t || t=""
    t="$(fold_digits "$t")"
    if [ -z "$t" ]; then REPLY_TG=""; return 0; fi
    if valid_tg_id "$t"; then REPLY_TG="$t"; return 0; fi
    warn "That is not a numeric Telegram ID (5-15 digits, e.g. 123456789; not the @username)."
  done
}

bot_username() { # bot_username TOKEN -> prints @username or nothing (token never on the command line)
  printf 'url = "https://api.telegram.org/bot%s/getMe"\n' "$1" \
    | curl -fsS -m 10 -K - 2>/dev/null | sed -n 's/.*"username":"\([^"]*\)".*/@\1/p'
}

check_dns() { # warn when a domain does not point here
  local sip d dip bad=0; sip="$(server_ip)"
  [ -z "$sip" ] && { warn "Could not detect this server's public IP; skipping the DNS check."; return 0; }
  for d in "$@"; do
    dip="$(domain_ip "$d")"
    if [ "$dip" = "$sip" ]; then ok "$d -> $dip"
    else warn "$d resolves to '${dip:-nothing}', this server is $sip"; bad=1; fi
  done
  if [ "$bad" = 1 ]; then
    warn "TLS certificates cannot be issued until the domains point at this server."
    if [ "$NONINTERACTIVE" = 1 ]; then
      if [ "$OPT_SKIP_DNS" = 1 ]; then warn "Continuing anyway (--skip-dns-check)."; return 0; fi
      err "Fix the DNS records first (a wrong record burns Let's Encrypt's 5 certificates/week limit), or pass --skip-dns-check when a CDN/proxy sits in front of the domains."
      return 1
    fi
    confirm "Continue anyway?" n || return 1
  fi
  return 0
}

banner() {
  clear 2>/dev/null || true
  printf '%s' "$CB"
  cat <<'EOF'
  __  __      _            _
 |  \/  | ___| | ___  _ __(_)_ __
 | |\/| |/ _ \ |/ _ \| '__| | '_ \
 | |  | |  __/ | (_) | |  | | | | |
 |_|  |_|\___|_|\___/|_|  |_|_| |_|
EOF
  printf '%s' "$C0"
  if installed; then
    local st="stopped"
    compose ps --status running --services 2>/dev/null | grep -qx api && st="running"
    printf '  store: %s   admin: %s   [%s]\n\n' "$(env_get MELORIN_DOMAIN)" "$(env_get MELORIN_ADMIN_DOMAIN)" "$st"
  else
    printf '  not installed yet - choose 1 to install\n\n'
  fi
}

# ---------------------------------------------------------------- 1) Install
install_usage() {
  cat <<'EOF'
Usage: melorin install [options]            (no options = the interactive questions)
  --domain D            store (sales site) domain, e.g. shop.example.com        [env DOMAIN]
  --admin-domain A      admin panel domain, e.g. admin.example.com              [env ADMIN_DOMAIN]
  --email E             login e-mail of the first admin                          [env ADMIN_EMAIL]
  --admin-tg ID         numeric Telegram ID of the main admin (optional)         [env ADMIN_TELEGRAM_ID]
  --store-name NAME     name customers see on the store (optional; empty = neutral default,
                        renamable later in the admin panel; never assumed to be "Melorin") [env MAIN_STORE_NAME]
  --bot-token-file F    file whose first line is the Telegram bot token (optional; or env MAIN_BOT_TOKEN)
  --external-proxy      ports 80/443 belong to your own reverse proxy; Melorin listens on 127.0.0.1:18080/18081/18000
  --skip-dns-check      do not refuse when the domains do not resolve to this server (CDN / proxy in front)
  --force               downgrade RAM / disk / OS-version failures to warnings
  -y, --yes             never ask: use the values above (also implied when there is no terminal)
EOF
}

set_install_opt() {
  case "$1" in
    --domain) OPT_DOMAIN="$2" ;;
    --admin-domain) OPT_ADMIN_DOMAIN="$2" ;;
    --email) OPT_EMAIL="$2" ;;
    --admin-tg) OPT_TG="$2" ;;
    --store-name) OPT_STORE_NAME="$2" ;;
    --bot-token-file) OPT_TOKEN_FILE="$2" ;;
  esac
}
parse_install_args() { # returns 2 on a usage error
  while [ $# -gt 0 ]; do
    case "$1" in
      -y|--yes|--non-interactive) ASSUME_YES=1; NONINTERACTIVE=1 ;;
      --skip-dns-check) OPT_SKIP_DNS=1 ;;
      --external-proxy) OPT_EXT=true ;;
      --force) MELORIN_FORCE=1; export MELORIN_FORCE ;;
      -h|--help) install_usage; exit 0 ;;
      --domain|--admin-domain|--email|--admin-tg|--store-name|--bot-token-file)
        [ $# -ge 2 ] || { err "$1 needs a value"; return 2; }
        set_install_opt "$1" "$2"; shift ;;
      --domain=*|--admin-domain=*|--email=*|--admin-tg=*|--store-name=*|--bot-token-file=*) set_install_opt "${1%%=*}" "${1#*=}" ;;
      --bot-token|--bot-token=*) err "The bot token must not be given on the command line (it would show up in 'ps' and the shell history): use MAIN_BOT_TOKEN=... or --bot-token-file FILE."; return 2 ;;
      *) err "Unknown install option: $1"; install_usage >&2; return 2 ;;
    esac
    shift
  done
}

install_lock_held() { # true while an install_server.sh process holds var/install.lock
  mkdir -p "$APP_DIR/var" || return 1
  ! ( flock -n 9 ) 9>"$APP_DIR/var/install.lock" 2>/dev/null
}

# Runs scripts/install_server.sh in its OWN SESSION (setsid) with the output going to the log file, and follows the log on the
# screen. Closing the terminal or losing the SSH connection no longer kills the install halfway (that used to lose the
# first-login password); Ctrl-C only stops following. The inputs arrive through the environment of this call.
run_install_detached() {
  local log="$MELORIN_LOG_FILE" rcf="$APP_DIR/var/install.rc" pidf="$APP_DIR/var/install.pid" tailpid waited=0 interrupted=0
  mkdir -p "$APP_DIR/var" || return 1
  if install_lock_held; then err "An installation is already running. Follow it with: tail -f $log"; return 75; fi
  rm -f "$rcf" "$pidf"
  ( umask 077; mkdir -p "$(dirname "$log")"; : >>"$log" ) 2>/dev/null || { err "Cannot write the log file $log"; return 1; }
  chmod 600 "$log" 2>/dev/null || true
  printf '\n===== install started %s =====\n' "$(date -u +%FT%TZ)" >>"$log"
  # The screen shows the installer's own messages; BuildKit's per-step noise (hundreds of "#12 ..." lines) stays in the log file.
  # MELORIN_VERBOSE=1 shows everything. The subshell is killed together with its tail/grep children below.
  if [ "${MELORIN_VERBOSE:-0}" = 1 ]; then ( tail -n 0 -f "$log" ) & tailpid=$!
  else ( tail -n 0 -f "$log" | grep --line-buffered -v -E '^#[0-9]+ |^[[:space:]]*$' ) & tailpid=$!; fi
  setsid -f bash -c 'echo $$ >"$2"; bash "$1" >>"$3" 2>&1 </dev/null; echo $? >"$4"' _ \
    "$APP_DIR/scripts/install_server.sh" "$pidf" "$log" "$rcf"
  trap 'interrupted=1' INT
  SECONDS=0
  while [ ! -s "$rcf" ] && [ "$interrupted" = 0 ]; do
    sleep 1
    # a heartbeat, so a long silent step (image build, npm ci) never looks like a hang
    if [ $((SECONDS % 45)) -eq 0 ] && [ "${MELORIN_VERBOSE:-0}" != 1 ]; then printf '   ... still working (%dm%02ds) - full log: %s\n' $((SECONDS / 60)) $((SECONDS % 60)) "$log"; fi
    if [ ! -s "$pidf" ]; then
      waited=$((waited + 1))
      if [ "$waited" -ge 15 ]; then echo 125 >"$rcf"; warn "The installer did not start."; fi
    elif [ ! -s "$rcf" ] && ! kill -0 "$(cat "$pidf")" 2>/dev/null; then
      sleep 2   # the exit code is written a moment after the process ends
      if [ ! -s "$rcf" ]; then echo 137 >"$rcf"; warn "The installer process disappeared (killed? out of memory?)."; fi
    fi
  done
  pkill -P "$tailpid" 2>/dev/null; kill "$tailpid" 2>/dev/null; wait "$tailpid" 2>/dev/null
  trap ':' INT
  if [ "$interrupted" = 1 ]; then
    echo; info "Stopped following. The installation keeps running in the background."
    info "Follow it: tail -f $log      Finished? cat $rcf   (0 = success)"
    return 0
  fi
  return "$(cat "$rcf")"
}

do_install() {
  local DOMAIN ADMIN_DOMAIN BOT="" ADMIN_EMAIL ADMIN_TG="" STORE_NAME="" ext="$EXTERNAL_PROXY" uname owner p bad=0 rc
  [ -n "$OPT_EXT" ] && ext="$OPT_EXT"

  if installed; then
    warn "Melorin is already installed (.env exists); it will never be overwritten."
    if [ "$ASSUME_YES" != 1 ]; then
      confirm "Re-run the installer to repair/re-apply the stack with the existing settings?" n || return 0
    fi
    DOMAIN="$(env_get MELORIN_DOMAIN)"; ADMIN_DOMAIN="$(env_get MELORIN_ADMIN_DOMAIN)"
    ADMIN_EMAIL="$(env_get MELORIN_BOOTSTRAP_ADMIN_EMAIL)"; ADMIN_TG="$(env_get MELORIN_BOOTSTRAP_ADMIN_TELEGRAM_ID)"
  else
    info "Checking this server..."
    PF_FAIL=0; preflight_system
    if [ "$PF_FAIL" -gt 0 ]; then err "This server does not meet the minimum requirements (above). Fix that, or accept the risk with --force."; return 1; fi

    if [ "$NONINTERACTIVE" = 1 ]; then
      # -------- unattended: every value comes from flags / environment and is validated here, before anything is touched
      DOMAIN="$(norm_domain "$OPT_DOMAIN")"; ADMIN_DOMAIN="$(norm_domain "$OPT_ADMIN_DOMAIN")"
      ADMIN_EMAIL="${OPT_EMAIL,,}"; ADMIN_EMAIL="${ADMIN_EMAIL//[[:space:]]/}"
      BOT="${MAIN_BOT_TOKEN:-}"
      if [ -n "$OPT_TOKEN_FILE" ]; then
        [ -r "$OPT_TOKEN_FILE" ] || { err "--bot-token-file: cannot read $OPT_TOKEN_FILE"; return 2; }
        BOT="$(head -n1 "$OPT_TOKEN_FILE")"
      fi
      BOT="${BOT//[[:space:]]/}"; ADMIN_TG="$(fold_digits "$OPT_TG")"; STORE_NAME="$OPT_STORE_NAME"
      valid_domain "$DOMAIN"       || { err "--domain: '${OPT_DOMAIN}' is not a valid domain (example: shop.example.com)"; bad=1; }
      valid_domain "$ADMIN_DOMAIN" || { err "--admin-domain: '${OPT_ADMIN_DOMAIN}' is not a valid domain (example: admin.example.com)"; bad=1; }
      if [ "$DOMAIN" = "$ADMIN_DOMAIN" ] && [ -n "$DOMAIN" ]; then err "--admin-domain must be different from --domain"; bad=1; fi
      valid_email "$ADMIN_EMAIL"   || { err "--email: '${OPT_EMAIL}' is not a usable address (.test/.local/.invalid/.onion domains are refused by the app's login validator)"; bad=1; }
      if [ -n "$BOT" ] && ! valid_token "$BOT"; then err "The bot token is malformed (expected 123456789:AA...)"; bad=1; fi
      if [ -n "$ADMIN_TG" ] && ! valid_tg_id "$ADMIN_TG"; then err "--admin-tg is not a numeric Telegram ID (5-15 digits; not the @username)"; bad=1; fi
      if [ "$bad" = 1 ]; then echo >&2; install_usage >&2; return 2; fi
      if [ -n "$BOT" ]; then
        uname="$(bot_username "$BOT")"
        if [ -n "$uname" ]; then ok "Bot token verified: $uname"; else warn "Could not verify the bot token with Telegram (network or wrong token); continuing."; fi
      fi
      if [ "$ext" != true ]; then check_dns "$DOMAIN" "$ADMIN_DOMAIN" || return 1; fi
    else
      # -------- interactive: the five questions
      echo
      echo "${CB}Five things are needed:${C0} store domain, admin domain, admin e-mail, bot token, admin Telegram ID (plus an optional store name)."
      echo "Both domains must already point (A record) to this server."
      echo
      ask_domain "1) Store (sales site) domain, e.g. shop.example.com" || return 1; DOMAIN="$REPLY_DOMAIN"
      while true; do
        ask_domain "2) Admin panel domain, e.g. admin.example.com" || return 1; ADMIN_DOMAIN="$REPLY_DOMAIN"
        [ "$ADMIN_DOMAIN" != "$DOMAIN" ] && break
        warn "The admin domain must be different from the store domain."
      done
      ask_email "3) Admin e-mail (login name of the first admin)" || return 1; ADMIN_EMAIL="$REPLY_EMAIL"
      ask_token; BOT="$REPLY_TOKEN"
      if [ -n "$BOT" ]; then
        uname="$(bot_username "$BOT")"
        if [ -n "$uname" ]; then ok "Bot token verified: $uname"
        else warn "Could not verify the token with Telegram (network or wrong token)."; confirm "Use it anyway?" n || return 1; fi
      else
        warn "No token: the Telegram bot will not start until you add it (menu 3)."
      fi
      ask_admin_tg "5)"; ADMIN_TG="$REPLY_TG"
      if [ -n "$ADMIN_TG" ]; then
        ok "Admin alerts will go to Telegram ID $ADMIN_TG (open the bot once and press Start so Telegram can deliver them)."
      else
        warn "No Telegram ID: admin alerts stay in the panel only (set it later: menu 3 -> Admin Telegram ID, or in the Admin panel)."
      fi
      ask_store_name "6)"; STORE_NAME="$REPLY_STORE_NAME"
      echo
      info "Checking DNS..."
      check_dns "$DOMAIN" "$ADMIN_DOMAIN" || return 1
    fi

    # Ports 80/443 are required by the bundled Caddy; say WHO holds them (a stock nginx/apache on the image is the usual culprit).
    if [ "$ext" != "true" ]; then
      for p in 80 443; do
        if owner="$(port_owner "$p")"; then
          warn "Port $p is already in use by $owner."
          if [ "$NONINTERACTIVE" = 1 ]; then
            err "Free port $p (e.g. systemctl disable --now nginx apache2), or install behind your own reverse proxy with --external-proxy."; return 1
          fi
          if confirm "Install behind your existing reverse proxy (EXTERNAL_PROXY mode)?" y; then ext=true; break
          else err "Free ports 80/443 and try again."; return 1; fi
        fi
      done
    fi
    echo
    echo "  Store domain : $DOMAIN"
    echo "  Admin domain : $ADMIN_DOMAIN"
    echo "  Admin e-mail : $ADMIN_EMAIL"
    echo "  Bot token    : $([ -n "$BOT" ] && echo set || echo not set)"
    echo "  Admin TG ID  : ${ADMIN_TG:-not set}"
    echo "  Store name   : ${STORE_NAME:-default (rename it in the admin panel)}"
    echo "  Proxy mode   : $([ "$ext" = true ] && echo 'external (loopback ports 18080/18081/18000)' || echo 'bundled Caddy (automatic TLS)')"
    echo
    if [ "$NONINTERACTIVE" != 1 ]; then confirm "Start the installation?" y || return 0; fi
  fi

  [ -x "$APP_DIR/scripts/install_server.sh" ] || chmod +x "$APP_DIR/scripts/install_server.sh"
  if installed; then info "Re-applying the stack with the existing settings (a few minutes)."
  else info "Installing. This takes about 5-15 minutes (the images are built on this server)."; fi
  info "It runs in the background with a log ($MELORIN_LOG_FILE): even if the connection drops, it carries on."
  (
    export MAIN_BOT_TOKEN="$BOT" ADMIN_TELEGRAM_ID="$ADMIN_TG" MAIN_STORE_NAME="$STORE_NAME" SKIP_BOT_PROMPT=1 MELORIN_PREFLIGHT_DONE=1 \
           DOMAIN="$DOMAIN" ADMIN_DOMAIN="$ADMIN_DOMAIN" ADMIN_EMAIL="$ADMIN_EMAIL" \
           EXTERNAL_PROXY="$ext" REPO_URL="$REPO_URL" REPO_REF="$REPO_REF" APP_DIR="$APP_DIR" \
           MELORIN_FORCE="${MELORIN_FORCE:-0}" MELORIN_LOG_FILE="$MELORIN_LOG_FILE"
    run_install_detached
  )
  rc=$?
  BOT=""
  load_mode
  if [ $rc -eq 75 ]; then return 1   # already running: run_install_detached said so
  elif [ $rc -eq 0 ]; then
    echo; ok "Installation finished. Open the menu any time with: melorin"
  else
    err "The installer stopped (code $rc). The reason is at the end of the log: tail -n 40 $MELORIN_LOG_FILE"
    err "Fix it and run the install again; it is safe to repeat."
  fi
  return $rc
}

# ---------------------------------------------------------------- 2) Update
resolve_ref() {
  if git rev-parse --verify --quiet "origin/${REPO_REF}^{commit}" >/dev/null; then echo "origin/${REPO_REF}"; else echo "$REPO_REF"; fi
}
do_update() {
  installed || { err "Not installed yet."; return 1; }
  if install_lock_held; then err "An installation is running right now; wait for it (tail -f $MELORIN_LOG_FILE)."; return 1; fi
  local before after
  before="$(git rev-parse --short HEAD 2>/dev/null)"
  git config core.fileMode false   # heals installs made before get.sh set it: chmod +x must not make the tree "dirty"
  info "Fetching ($REPO_REF)..."
  retry 3 5 git fetch --quiet --tags origin || { err "git fetch failed (network?)"; return 1; }
  # A moving ref (main) would leave an install stuck behind newer releases: prefer the newest vX.Y.Z tag when one exists (audit V-32a).
  if git rev-parse --verify --quiet "origin/${REPO_REF}^{commit}" >/dev/null; then
    # strict vX.Y.Z only: a release candidate (v1.0.0-rc1) must neither win over v1.0.0 nor count as "the newest release"
    local newest; newest="$(git tag --list 'v[0-9]*' | { grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' || true; } | sort -V | tail -n1)"
    if [ -n "$newest" ]; then info "Newest release tag is $newest; updating to it instead of moving '$REPO_REF'."; REPO_REF="$newest"; fi
  fi
  # Optional release-signature gate (audit V-020): MELORIN_REQUIRE_SIGNED_TAGS=1 refuses any ref that is not a tag signed by a key
  # already in this host's GPG keyring (import the maintainer's public key first). Off by default so unsigned pre-release tags still work.
  if [ "${MELORIN_REQUIRE_SIGNED_TAGS:-0}" = "1" ]; then
    git rev-parse --verify --quiet "refs/tags/${REPO_REF}" >/dev/null \
      || { err "MELORIN_REQUIRE_SIGNED_TAGS=1 but '$REPO_REF' is not a tag."; return 1; }
    git verify-tag "$REPO_REF" >/dev/null 2>&1 \
      || { err "Tag $REPO_REF has no valid signature from a trusted key - refusing to update."; return 1; }
    info "Tag $REPO_REF signature verified."
  fi
  git -c advice.detachedHead=false checkout --quiet --detach "$(resolve_ref)" \
    || { err "Checkout failed - there are local edits to tracked files in $APP_DIR."; return 1; }
  after="$(git rev-parse --short HEAD)"
  chmod +x melorin.sh scripts/*.sh 2>/dev/null || true
  if [ "$before" = "$after" ]; then info "Already at $after; rebuilding anyway."; else info "Updating $before -> $after"; fi
  ( umask 077; mkdir -p var; cp -p .env var/env.before-update )
  # Least-privilege bot-runner secrets (docs/16): older installs get them on update; Core then retires the shared secret.
  for k in MELORIN_MAIN_BOT_SECRET MELORIN_RESELLER_BOT_SECRET; do
    [ -n "$(env_get "$k")" ] && continue
    sec="$(openssl rand -hex 32 2>/dev/null)"
    [ "${#sec}" -ge 32 ] || { err "Could not generate $k (is openssl installed?). Nothing was changed."; return 1; }
    env_set "$k" "$sec" && info "Generated $k."
  done
  # A manual update builds on this host: stop pointing the stack at registry images of an older commit (see scripts/deploy.sh).
  if [ -n "$(env_get MELORIN_IMAGE_TAG)" ]; then env_set MELORIN_IMAGE_TAG local; fi
  compose build                          || { err "Build failed."; return 1; }
  # Never migrate without a restore point (audit V-020): take an encrypted backup with the CURRENT stack first (--no-deps: the new
  # migrate service must not run before it). Set MELORIN_SKIP_PRE_UPDATE_BACKUP=1 only if you have a fresh backup elsewhere.
  if [ "${MELORIN_SKIP_PRE_UPDATE_BACKUP:-0}" != "1" ]; then
    info "Taking a pre-update backup..."
    compose run -T --rm --no-deps backup python -c "import asyncio; from melorin.worker import jobs; print(asyncio.run(jobs.backup_job()))" </dev/null \
      || { err "Pre-update backup failed - nothing was migrated. Fix the backup (menu: status) or set MELORIN_SKIP_PRE_UPDATE_BACKUP=1."; return 1; }
  fi
  compose run -T --rm api alembic upgrade head </dev/null || { err "Migration failed - services were NOT restarted. Roll back the code with: git checkout --detach $before"; return 1; }
  compose up -d --remove-orphans         || { err "Could not start the services."; return 1; }
  ok "Updated to $after. Your .env was kept (copy: var/env.before-update)."
  if [ "$before" != "$after" ]; then info "If this menu changed, close it and run 'melorin' again."; fi
  return 0
}

# ---------------------------------------------------------------- 3) Edit .env
apply_env() {
  if confirm "Apply now (recreate containers)?" y; then
    compose up -d --force-recreate && ok "Applied." || err "Apply failed; see: compose logs"
  else
    warn "Not applied yet. Run menu 5 -> restart to apply."
  fi
}
set_cors() { env_set MELORIN_CORS_ORIGINS "[\"https://$(env_get MELORIN_DOMAIN)\",\"https://$(env_get MELORIN_ADMIN_DOMAIN)\"]"; }

edit_env() {
  installed || { err "Not installed yet."; return 1; }
  while true; do
    banner
    cat <<EOF
  ${CB}Edit .env${C0}
   1) Bot token
   2) Store domain   ($(env_get MELORIN_DOMAIN))
   3) Admin domain   ($(env_get MELORIN_ADMIN_DOMAIN))
   4) Open .env in an editor
   5) Admin Telegram ID   ($(env_get MELORIN_BOOTSTRAP_ADMIN_TELEGRAM_ID))
   0) Back
EOF
    read -r -p "Select: " c || return 0
    case "$c" in
      1) ask_token
         if [ -z "$REPLY_TOKEN" ]; then warn "Nothing changed."; else
           local u; u="$(bot_username "$REPLY_TOKEN")"
           [ -n "$u" ] && ok "Token verified: $u" || warn "Could not verify the token with Telegram."
           # Keep the alert receiver on the same bot unless the operator configured a different alert bot on purpose (T05).
           local oldtok; oldtok="$(env_get MELORIN_MAIN_BOT_TOKEN)"
           if [ -z "$(env_get ALERT_TELEGRAM_BOT_TOKEN)" ] || [ "$(env_get ALERT_TELEGRAM_BOT_TOKEN)" = "$oldtok" ]; then
             env_set ALERT_TELEGRAM_BOT_TOKEN "$REPLY_TOKEN"
           fi
           env_set MELORIN_TELEGRAM_TOKEN "$REPLY_TOKEN"; env_set MELORIN_MAIN_BOT_TOKEN "$REPLY_TOKEN"
           REPLY_TOKEN=""; ok "Saved."; apply_env
         fi; pause ;;
      2) ask_domain "New store domain"
         env_set MELORIN_DOMAIN "$REPLY_DOMAIN"
         env_set MELORIN_STORE_WEB_URL "https://$REPLY_DOMAIN"
         env_set MELORIN_PUBLIC_API_URL "https://$REPLY_DOMAIN"
         set_cors; check_dns "$REPLY_DOMAIN"; apply_env; pause ;;
      3) ask_domain "New admin domain"
         env_set MELORIN_ADMIN_DOMAIN "$REPLY_DOMAIN"
         set_cors; check_dns "$REPLY_DOMAIN"; apply_env; pause ;;
      4) local ed="${EDITOR:-}"; [ -z "$ed" ] && for ed in nano vi; do command -v "$ed" >/dev/null && break; done
         "$ed" "$ENV_FILE_PATH"; chmod 600 "$ENV_FILE_PATH"; apply_env; pause ;;
      5) ask_admin_tg "New"
         if [ -z "$REPLY_TG" ]; then warn "Nothing changed."; else
           # Linked in the database (the running API is used: no restart needed) and remembered in .env for repair runs.
           if compose exec -T api python -m melorin.cli set-admin-telegram "$(env_get MELORIN_BOOTSTRAP_ADMIN_EMAIL)" "$REPLY_TG"; then
             local oldtg; oldtg="$(env_get MELORIN_BOOTSTRAP_ADMIN_TELEGRAM_ID)"
             if [ -z "$(env_get ALERT_TELEGRAM_CHAT_ID)" ] || [ "$(env_get ALERT_TELEGRAM_CHAT_ID)" = "$oldtg" ]; then
               env_set ALERT_TELEGRAM_CHAT_ID "$REPLY_TG"   # T05: alerts follow the admin ID unless set separately
             fi
             env_set MELORIN_BOOTSTRAP_ADMIN_TELEGRAM_ID "$REPLY_TG"; ok "Saved. Open the main bot once and press Start."
           else err "Could not link the Telegram ID (is the stack running? see the message above)."; fi
         fi; pause ;;
      0|"") return 0 ;;
      *) warn "Invalid choice." ;;
    esac
  done
}

# ---------------------------------------------------------------- 4) Web panel
health_check() {
  compose exec -T api python - <<'PY'
import json, os, urllib.error, urllib.request
req = urllib.request.Request("http://127.0.0.1:8000/health/ready",
                             headers={"X-Melorin-Health-Token": os.environ.get("MELORIN_HEALTH_TOKEN", "")})
try:
    r = urllib.request.urlopen(req, timeout=8); code, body = r.status, r.read()
except urllib.error.HTTPError as e:
    code, body = e.code, e.read()
print("HTTP", code)
print(json.dumps(json.loads(body), indent=2))
PY
}

web_panel() {
  installed || { err "Not installed yet."; return 1; }
  while true; do
    banner
    cat <<EOF
  ${CB}Web panel${C0}
   Store : https://$(env_get MELORIN_DOMAIN)
   Admin : https://$(env_get MELORIN_ADMIN_DOMAIN)
   Login : $(env_get MELORIN_BOOTSTRAP_ADMIN_EMAIL)

   1) Health check (database / redis / worker)
   2) Reset admin password
   3) Disable admin IP allowlist (if you locked yourself out)
   0) Back
EOF
    read -r -p "Select: " c || return 0
    case "$c" in
      1) health_check; pause ;;
      2) local pw; pw="$(openssl rand -base64 36 | tr -d '/+=\n' | head -c 32)"
         echo "A strong password (min 24 chars) is required. Suggested one - copy it now:"
         echo "  ${CB}${pw}${C0}"
         echo "Paste it (or your own) at the hidden prompts below. The existing TOTP stays unchanged."
         compose exec api python -m melorin.cli reset-admin-password "$(env_get MELORIN_BOOTSTRAP_ADMIN_EMAIL)"
         pw=""; pause ;;
      3) compose exec -T api python -m melorin.cli disable-admin-ip-allowlist; pause ;;
      0|"") return 0 ;;
      *) warn "Invalid choice." ;;
    esac
  done
}

# ---------------------------------------------------------------- 5) Service
service_menu() {
  installed || { err "Not installed yet."; return 1; }
  while true; do
    banner
    cat <<EOF
  ${CB}Service${C0}
   1) Status of containers
   2) Start
   3) Stop
   4) Restart all
   5) Restart one service
   6) Logs (Ctrl-C to leave)
   0) Back
EOF
    read -r -p "Select: " c || return 0
    case "$c" in
      1) compose ps; pause ;;
      2) compose up -d && ok "Started."; pause ;;
      3) confirm "Stop all services (the store goes offline)?" n && compose stop && ok "Stopped."; pause ;;
      4) compose restart && ok "Restarted."; pause ;;
      5|6) local svc
         echo "Services: $(compose config --services 2>/dev/null | tr '\n' ' ')"
         read -r -p "Service name (Enter = all): " svc || svc=""
         if [ "$c" = 5 ]; then compose restart ${svc:+"$svc"} && ok "Restarted."; pause
         else compose logs --tail=150 -f ${svc:+"$svc"}; fi ;;
      0|"") return 0 ;;
      *) warn "Invalid choice." ;;
    esac
  done
}

# ---------------------------------------------------------------- 6) Status
do_status() {
  installed || { err "Not installed yet."; return 1; }
  local dom adm tok u code
  dom="$(env_get MELORIN_DOMAIN)"; adm="$(env_get MELORIN_ADMIN_DOMAIN)"; tok="$(env_get MELORIN_TELEGRAM_TOKEN)"
  echo "${CB}Melorin status${C0}"
  echo "  Version   : $(git rev-parse --short HEAD 2>/dev/null) ($REPO_REF)   mode: $([ "$EXTERNAL_PROXY" = true ] && echo external-proxy || echo bundled-caddy)"
  echo "  Store     : https://$dom"
  echo "  Admin     : https://$adm"
  if [ -n "$tok" ]; then u="$(bot_username "$tok")"; echo "  Bot       : ${u:-token set (could not reach Telegram)}"; else echo "  Bot       : ${CY}token NOT set${C0}"; fi
  echo
  compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Health}}\t{{.Status}}' 2>/dev/null || compose ps
  echo
  echo "  API ready :"; health_check 2>/dev/null | sed 's/^/    /' || warn "API not reachable"
  if [ "$EXTERNAL_PROXY" != true ]; then
    for d in "$dom" "$adm"; do
      code="$(curl -sS -m 8 -o /dev/null -w '%{http_code}' "https://$d/health/live" 2>/dev/null || echo ---)"
      echo "  https://$d/health/live -> $code"
    done
  fi
  echo
  echo "  Disk free : $(df -h / | awk 'NR==2{print $4" of "$2" ("$5" used)"}')"
  echo "  Memory    : $(free -h | awk '/^Mem:/{print $7" available of "$2}')"
  [ -s secrets/backup/age-identity.txt ] && echo "  Backup key: present (keep a copy OFF this server)" || warn "Backup key missing"
  [ -f /etc/cron.d/melorin-ops-watch ] && echo "  Recorder  : active (var/ops-log.md)" || warn "Change recorder not installed"
}

# ---------------------------------------------------------------- 7) Uninstall
do_uninstall() {
  # APP_DIR comes from the location of this script: refuse anything that is not clearly a Melorin checkout.
  case "$APP_DIR" in
    ""|/|/usr|/usr/*|/bin|/sbin|/lib|/etc|/var|/root|/home|/boot|/opt|/srv|/mnt|/tmp)
      err "Refusing to delete '$APP_DIR': that is not a Melorin install directory."; return 1 ;;
  esac
  if [ ! -d "$APP_DIR/.git" ] || [ ! -f "$APP_DIR/melorin.sh" ] || [ ! -f "$APP_DIR/docker-compose.yml" ]; then
    err "Refusing to delete '$APP_DIR': it does not look like a Melorin checkout."; return 1
  fi
  echo "${CR}This removes Melorin from this server.${C0}"
  echo "  - containers, images and Docker volumes (database, redis)"
  echo "  - TLS certificates are KEPT (volume caddy_data) so a reinstall does not hit the Let's Encrypt limit of 5 certificates/7 days"
  echo "  - $APP_DIR (including .env and the backup key secrets/backup/)"
  echo "  - the 'melorin' command and the change-recorder cron job"
  echo "Docker itself is not removed."
  echo
  warn "Copy $APP_DIR/secrets/backup/age-identity.txt and any backups you need BEFORE continuing."
  local a; read -r -p "Type DELETE to confirm: " a || return 0
  [ "$a" = "DELETE" ] || { info "Cancelled."; return 0; }
  if installed; then
    local pj; pj="$(compose config --format json 2>/dev/null | sed -n 's/^  "name": "\([^"]*\)".*/\1/p' | head -1)"; pj="${pj:-$(basename "$APP_DIR")}"
    compose down --rmi local --remove-orphans || warn "compose down reported errors."
    # remove every volume of the project EXCEPT the certificates (caddy_data/caddy_config)
    docker volume ls -q --filter "label=com.docker.compose.project=$pj" | grep -vE "_caddy_(data|config)$" | xargs -r docker volume rm >/dev/null 2>&1 || true
    ok "Volumes removed; TLS certificates kept (docker volume rm ${pj}_caddy_data ${pj}_caddy_config to delete them too)."
  fi
  rm -f /etc/cron.d/melorin-ops-watch "$LINK"
  cd / && rm -rf "$APP_DIR"
  ok "Melorin was removed."
  exit 0
}

# ---------------------------------------------------------------- 8) Doctor
# Read-only: tells what would stop (or already stops) Melorin from working. Exit code = number of FAIL lines.
do_doctor() {
  PF_FAIL=0; PF_WARN=0
  echo "${CB}Melorin doctor${C0}  (read-only: nothing is changed)"
  echo; echo "${CB}System${C0}";  preflight_system
  echo; echo "${CB}Docker${C0}";  preflight_docker
  echo; echo "${CB}Network${C0}"; preflight_network
  if installed; then
    echo; echo "${CB}This installation${C0}"
    local k mode dom adm
    for k in MELORIN_DOMAIN MELORIN_ADMIN_DOMAIN MELORIN_JWT_SECRET MELORIN_ENCRYPTION_KEY POSTGRES_PASSWORD MELORIN_DATABASE_URL \
             MELORIN_BOT_SERVICE_SECRET MELORIN_MAIN_BOT_SECRET MELORIN_RESELLER_BOT_SECRET MELORIN_METRICS_TOKEN MELORIN_HEALTH_TOKEN; do
      [ -n "$(env_get "$k")" ] || pf_fail ".env: $k is empty or missing"
    done
    mode="$(stat -c %a "$ENV_FILE_PATH" 2>/dev/null)"
    if [ "$mode" = 600 ]; then pf_ok ".env permissions 600"; else pf_warn ".env permissions are $mode (should be 600): chmod 600 $ENV_FILE_PATH"; fi
    [ -n "$(env_get MELORIN_TELEGRAM_TOKEN)" ] && pf_ok "Telegram bot token is set" || pf_warn "Telegram bot token is not set (menu 3 -> Bot token)"
    [ -s secrets/backup/age-identity.txt ] && pf_ok "Backup key present (keep a copy OFF this server)" || pf_warn "Backup key secrets/backup/age-identity.txt is missing"
    if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then pf_warn "Tracked files were edited on this server; updates will refuse until 'git stash'"; else pf_ok "Checkout is clean"; fi
    if [ "$EXTERNAL_PROXY" != true ]; then
      dom="$(env_get MELORIN_DOMAIN)"; adm="$(env_get MELORIN_ADMIN_DOMAIN)"; preflight_dns "$dom" "$adm"
    fi
    local bad
    bad="$(compose ps --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null | awk '$2!="running" && $2!="" || $3=="unhealthy" {print $1":"$2"/"$3}' | tr '\n' ' ')"
    if [ -z "$bad" ]; then pf_ok "All containers running"; else pf_fail "Containers not healthy: $bad (logs: melorin logs <service>)"; fi
  elif [ "$EXTERNAL_PROXY" != true ]; then
    echo; echo "${CB}Ports (the bundled Caddy needs 80 and 443)${C0}"; preflight_ports
  fi
  echo
  if [ "$PF_FAIL" -gt 0 ]; then err "$PF_FAIL problem(s) must be fixed, $PF_WARN warning(s)."
  elif [ "$PF_WARN" -gt 0 ]; then warn "No blocking problem; $PF_WARN warning(s) above."
  else ok "Everything looks good."; fi
  [ "$PF_FAIL" -eq 0 ]
}

usage() {
  cat <<'EOF'
melorin - manage this Melorin server
  melorin                       the interactive menu (needs a terminal)
  melorin install [options]     install; with --domain/--admin-domain/--email/--yes it asks nothing (melorin install --help)
  melorin update                pull the newest release, back up, migrate, restart (.env is kept)
  melorin status                health summary
  melorin doctor                read-only check of this server and this installation
  melorin panel                 web panel URLs, health, admin password reset
  melorin restart | logs [service]
EOF
}

# ---------------------------------------------------------------- menu
main_menu() {
  while true; do
    banner
    cat <<EOF
   ${CB}1${C0}) Install      first-time setup (domains, e-mail, bot token)
   ${CB}2${C0}) Update       latest code, migrate, restart (.env kept)
   ${CB}3${C0}) Edit .env    bot token / domains / editor
   ${CB}4${C0}) Web panel    URLs, health, admin password reset
   ${CB}5${C0}) Service      status / start / stop / restart / logs
   ${CB}6${C0}) Status       health summary
   ${CB}7${C0}) Uninstall    remove everything
   ${CB}8${C0}) Doctor       check this server / find problems
   ${CB}0${C0}) Exit
EOF
    read -r -p "Select: " c || exit 0
    case "$c" in
      1) do_install; pause ;;
      2) do_update; pause ;;
      3) edit_env ;;
      4) web_panel ;;
      5) service_menu ;;
      6) do_status; pause ;;
      7) do_uninstall; pause ;;
      8) do_doctor; pause ;;
      0|q|"") exit 0 ;;
      *) warn "Invalid choice."; sleep 1 ;;
    esac
  done
}

cmd="${1:-menu}"; [ $# -gt 0 ] && shift
case "$cmd" in
  menu)
    if [ "$HAVE_TTY" != 1 ]; then
      err "The menu needs a terminal, and this session has none (ssh without -t, cron, cloud-init...)."
      echo "  Interactive: connect with 'ssh -t host' and run: melorin" >&2
      echo "  Unattended : melorin install --domain D --admin-domain A --email E --yes   (melorin install --help)" >&2
      exit 2
    fi
    main_menu ;;
  install) parse_install_args "$@" || exit $?; do_install; exit $? ;;
  update)  do_update; exit $? ;;
  status)  do_status ;;
  doctor)  do_doctor; exit $? ;;
  panel)   web_panel ;;
  restart) installed && compose restart ;;
  logs)    installed && compose logs --tail=150 -f ${1:+"$1"} ;;
  help|-h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
