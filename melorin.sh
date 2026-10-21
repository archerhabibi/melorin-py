#!/usr/bin/env bash
# Melorin management menu.   Open it with:  melorin   (or: bash melorin.sh)
#
#   1) Install    quiet install -> asks only: store domain, admin domain, admin e-mail, bot token
#   2) Update     pull latest code, rebuild, migrate, restart (.env is kept)
#   3) Edit .env  bot token / domains / open the file in an editor
#   4) Web panel  URLs, health check, admin password reset
#   5) Service    status / start / stop / restart / logs
#   6) Status     health summary
#   7) Uninstall  full removal
#   0) Exit
#
# Shortcuts:  melorin install|update|status|restart|logs|panel
set -uo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
APP_DIR="$(cd "$(dirname "$SELF")" && pwd)"
REPO_URL="${MELORIN_REPO_URL:-https://github.com/archerhabibi/melorin-py.git}"
LINK="/usr/local/bin/melorin"
trap ':' INT   # Ctrl-C stops a running child (e.g. logs) but keeps the menu alive

# When started through a pipe (curl | bash) read answers from the terminal.
if [ ! -t 0 ] && [ -r /dev/tty ]; then exec </dev/tty; fi

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

norm_domain() { # strip scheme, path, port-less, lowercase
  local d="${1,,}"; d="${d#http://}"; d="${d#https://}"; d="${d%%/*}"; d="${d%.}"; printf '%s' "$d"
}
valid_domain() { [[ "$1" =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]]; }
valid_token()  { [[ "$1" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]]; }

ask_domain() { # ask_domain "label" -> sets REPLY_DOMAIN
  local raw
  while true; do
    read -r -p "$1: " raw || return 1
    REPLY_DOMAIN="$(norm_domain "$raw")"
    valid_domain "$REPLY_DOMAIN" && return 0
    warn "Not a valid domain (example: shop.example.com)."
  done
}

valid_email() { [[ "$1" =~ ^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$ ]]; }
ask_email() { # sets REPLY_EMAIL
  local e
  while true; do
    read -r -p "$1: " e || return 1
    e="${e,,}"; e="${e// /}"
    if valid_email "$e"; then REPLY_EMAIL="$e"; return 0; fi
    warn "Not a valid e-mail address (example: you@example.com)."
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

bot_username() { # bot_username TOKEN -> prints @username or nothing (token never on the command line)
  printf 'url = "https://api.telegram.org/bot%s/getMe"\n' "$1" \
    | curl -fsS -m 10 -K - 2>/dev/null | sed -n 's/.*"username":"\([^"]*\)".*/@\1/p'
}

server_ip() { curl -4 -fsS -m 6 https://api.ipify.org 2>/dev/null || curl -4 -fsS -m 6 https://ifconfig.me 2>/dev/null || true; }
domain_ip() { getent ahostsv4 "$1" 2>/dev/null | awk '{print $1; exit}'; }

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
    confirm "Continue anyway?" n || return 1
  fi
  return 0
}

port_busy() { ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"; }

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
do_install() {
  local DOMAIN ADMIN_DOMAIN BOT ADMIN_EMAIL ext="$EXTERNAL_PROXY" uname

  if installed; then
    warn "Melorin is already installed (.env exists); it will never be overwritten."
    confirm "Re-run the installer to repair/re-apply the stack with the existing settings?" n || return 0
    DOMAIN="$(env_get MELORIN_DOMAIN)"; ADMIN_DOMAIN="$(env_get MELORIN_ADMIN_DOMAIN)"
    ADMIN_EMAIL="$(env_get MELORIN_BOOTSTRAP_ADMIN_EMAIL)"; BOT=""
  else
    echo
    echo "${CB}Four things are needed:${C0} store domain, admin domain, admin e-mail, bot token."
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
    echo
    info "Checking DNS..."
    check_dns "$DOMAIN" "$ADMIN_DOMAIN" || return 1

    # Ports 80/443 are required by the bundled Caddy.
    if [ "$ext" != "true" ] && { port_busy 80 || port_busy 443; }; then
      warn "Port 80 and/or 443 is already in use on this server."
      if confirm "Install behind your existing reverse proxy (EXTERNAL_PROXY mode)?" y; then ext=true
      else err "Free ports 80/443 and try again."; return 1; fi
    fi
    echo
    echo "  Store domain : $DOMAIN"
    echo "  Admin domain : $ADMIN_DOMAIN"
    echo "  Admin e-mail : $ADMIN_EMAIL"
    echo "  Bot token    : $([ -n "$BOT" ] && echo set || echo not set)"
    echo "  Proxy mode   : $([ "$ext" = true ] && echo 'external (loopback ports 18080/18081/18000)' || echo 'bundled Caddy (automatic TLS)')"
    echo
    confirm "Start the installation?" y || return 0
  fi

  [ -x "$APP_DIR/scripts/install_server.sh" ] || chmod +x "$APP_DIR/scripts/install_server.sh"
  MAIN_BOT_TOKEN="$BOT" SKIP_BOT_PROMPT=1 \
  DOMAIN="$DOMAIN" ADMIN_DOMAIN="$ADMIN_DOMAIN" ADMIN_EMAIL="$ADMIN_EMAIL" \
  EXTERNAL_PROXY="$ext" REPO_URL="$REPO_URL" REPO_REF="$REPO_REF" APP_DIR="$APP_DIR" \
    bash "$APP_DIR/scripts/install_server.sh"
  local rc=$?
  BOT=""
  load_mode
  if [ $rc -eq 0 ]; then
    echo; ok "Installation finished. Open the menu any time with: melorin"
  else
    err "Installer exited with code $rc - fix the problem above and run the install again (it is safe to repeat)."
  fi
}

# ---------------------------------------------------------------- 2) Update
resolve_ref() {
  if git rev-parse --verify --quiet "origin/${REPO_REF}^{commit}" >/dev/null; then echo "origin/${REPO_REF}"; else echo "$REPO_REF"; fi
}
do_update() {
  installed || { err "Not installed yet."; return 1; }
  local before after
  before="$(git rev-parse --short HEAD 2>/dev/null)"
  info "Fetching ($REPO_REF)..."
  git fetch --quiet --tags origin || { err "git fetch failed (network?)"; return 1; }
  git -c advice.detachedHead=false checkout --quiet --detach "$(resolve_ref)" \
    || { err "Checkout failed - there are local edits to tracked files in $APP_DIR."; return 1; }
  after="$(git rev-parse --short HEAD)"
  chmod +x melorin.sh scripts/*.sh 2>/dev/null || true
  if [ "$before" = "$after" ]; then info "Already at $after; rebuilding anyway."; else info "Updating $before -> $after"; fi
  ( umask 077; mkdir -p var; cp -p .env var/env.before-update )
  # Least-privilege bot-runner secrets (docs/16): older installs get them on update; Core then retires the shared secret.
  for k in MELORIN_MAIN_BOT_SECRET MELORIN_RESELLER_BOT_SECRET; do
    [ -n "$(env_get "$k")" ] || { env_set "$k" "$(openssl rand -hex 32)" && info "Generated $k."; }
  done
  compose build                          || { err "Build failed."; return 1; }
  compose run --rm api alembic upgrade head || { err "Migration failed - services were NOT restarted."; return 1; }
  compose up -d --remove-orphans         || { err "Could not start the services."; return 1; }
  ok "Updated to $after. Your .env was kept (copy: var/env.before-update)."
  [ "$before" != "$after" ] && info "If this menu changed, close it and run 'melorin' again."
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
   0) Back
EOF
    read -r -p "Select: " c || return 0
    case "$c" in
      1) ask_token
         if [ -z "$REPLY_TOKEN" ]; then warn "Nothing changed."; else
           local u; u="$(bot_username "$REPLY_TOKEN")"
           [ -n "$u" ] && ok "Token verified: $u" || warn "Could not verify the token with Telegram."
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
  echo "${CR}This removes Melorin from this server.${C0}"
  echo "  - containers, images and Docker volumes (database, redis, certificates)"
  echo "  - $APP_DIR (including .env and the backup key secrets/backup/)"
  echo "  - the 'melorin' command and the change-recorder cron job"
  echo "Docker itself is not removed."
  echo
  warn "Copy $APP_DIR/secrets/backup/age-identity.txt and any backups you need BEFORE continuing."
  local a; read -r -p "Type DELETE to confirm: " a || return 0
  [ "$a" = "DELETE" ] || { info "Cancelled."; return 0; }
  if installed; then compose down -v --rmi local --remove-orphans || warn "compose down reported errors."; fi
  rm -f /etc/cron.d/melorin-ops-watch "$LINK"
  cd / && rm -rf "$APP_DIR"
  ok "Melorin was removed."
  exit 0
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
      0|q|"") exit 0 ;;
      *) warn "Invalid choice."; sleep 1 ;;
    esac
  done
}

case "${1:-menu}" in
  menu)    main_menu ;;
  install) do_install ;;
  update)  do_update ;;
  status)  do_status ;;
  panel)   web_panel ;;
  restart) installed && compose restart ;;
  logs)    installed && compose logs --tail=150 -f ${2:+"$2"} ;;
  *) echo "Usage: melorin [install|update|status|panel|restart|logs [service]]"; exit 2 ;;
esac
