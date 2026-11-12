#!/usr/bin/env bash
# Melorin post-install step: host basics that every production install needs, plus a verification report.
# Called by scripts/install_server.sh at the end (non-fatal) and safe to run again at any time:
#
#   sudo bash scripts/post_install.sh
#
# Environment (all optional):
#   POST_INSTALL=0        skip everything (read by install_server.sh)
#   SWAP_GB=2             swap file size in GiB, 0 = skip       (4 GB hosts run close to the container memory caps)
#   ENABLE_UFW=1          allow SSH/80/443 and enable ufw       (0 = skip; never closes the detected SSH port)
#   ENABLE_FAIL2BAN=1     install fail2ban with the default sshd jail (0 = skip)
#   BOOTSTRAP_PASSWORD / BOOTSTRAP_TOTP   one-time admin credentials; saved to /root/melorin-credentials.txt (mode 600)
set -uo pipefail
umask 022

APP_DIR="${APP_DIR:-/opt/melorin}"
SWAP_GB="${SWAP_GB:-2}"
ENABLE_UFW="${ENABLE_UFW:-1}"
ENABLE_FAIL2BAN="${ENABLE_FAIL2BAN:-1}"
CRED_FILE="${CRED_FILE:-/root/melorin-credentials.txt}"
ok()   { printf '  \033[32m[ok]\033[0m   %s\n' "$*"; }
warnx(){ printf '  \033[33m[warn]\033[0m %s\n' "$*"; WARNS=$((WARNS+1)); }
say()  { printf '\033[1;36m>>\033[0m %s\n' "$*"; }
WARNS=0
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
cd "$APP_DIR" || exit 1
env_get() { sed -n "s/^$1=//p" .env | head -1; }

say "Post-install: host basics"

# 1) one-time credentials: the password is removed from .env after bootstrap, so a scrolled terminal would lose it.
if [ -n "${BOOTSTRAP_PASSWORD:-}${BOOTSTRAP_TOTP:-}" ]; then
  ( umask 077
    {
      echo "# Melorin first-login credentials (created $(date -u +%FT%TZ)). Change the password, add the TOTP seed to an authenticator, then DELETE this file."
      echo "admin_url=https://$(env_get MELORIN_ADMIN_DOMAIN)"
      echo "admin_email=$(env_get MELORIN_BOOTSTRAP_ADMIN_EMAIL)"
      [ -n "${BOOTSTRAP_PASSWORD:-}" ] && echo "password=${BOOTSTRAP_PASSWORD}"
      [ -n "${BOOTSTRAP_TOTP:-}" ] && echo "totp_seed=${BOOTSTRAP_TOTP}"
    } > "$CRED_FILE" )
  chmod 600 "$CRED_FILE"; ok "first-login credentials saved to $CRED_FILE (mode 600): delete it after the first login"
fi

# 2) swap: container caps add up to ~3.5 GiB on a 4 GB host; swap turns an OOM kill into a slow moment.
if [ "$SWAP_GB" != "0" ]; then
  if swapon --show --noheadings 2>/dev/null | grep -q .; then ok "swap already active"
  else
    free_gb=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
    if [ "${free_gb:-0}" -gt $((SWAP_GB + 5)) ] \
       && { fallocate -l "${SWAP_GB}G" /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=$((SWAP_GB*1024)) status=none; } \
       && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile; then
      grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
      sysctl -w vm.swappiness=10 >/dev/null; echo 'vm.swappiness=10' > /etc/sysctl.d/99-melorin-swap.conf
      ok "${SWAP_GB} GiB swap enabled"
    else warnx "could not create swap (disk space?)"; fi
  fi
fi

# 3) firewall: SSH (detected, always allowed first) + 80/443. Docker bypasses ufw for published ports, so the stack only
#    publishes 80/443 anyway; ufw protects everything else on the host.
if [ "$ENABLE_UFW" = "1" ]; then
  command -v ufw >/dev/null 2>&1 || { apt-get update -y >/dev/null 2>&1; DEBIAN_FRONTEND=noninteractive apt-get install -y ufw >/dev/null 2>&1; }
  if command -v ufw >/dev/null 2>&1; then
    if ufw status | grep -q 'Status: active'; then ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ok "ufw already active (80/443 ensured)"
    else
      ssh_ports="$(ss -tlnpH 2>/dev/null | awk '/sshd/ {n=split($4,a,":"); print a[n]}' | sort -u)"; ssh_ports="${ssh_ports:-22}"
      ufw default deny incoming >/dev/null; ufw default allow outgoing >/dev/null
      for p in $ssh_ports; do ufw allow "${p}/tcp" >/dev/null; done
      ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
      ufw --force enable >/dev/null && ok "ufw enabled (ssh: $(echo $ssh_ports | tr '\n' ' '), 80, 443)" || warnx "ufw could not be enabled"
    fi
  else warnx "ufw not available"; fi
fi

# 4) fail2ban: the Ubuntu default jail already watches sshd.
if [ "$ENABLE_FAIL2BAN" = "1" ]; then
  command -v fail2ban-client >/dev/null 2>&1 || { apt-get update -y >/dev/null 2>&1; DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban >/dev/null 2>&1; }
  if command -v fail2ban-client >/dev/null 2>&1; then
    systemctl enable --now fail2ban >/dev/null 2>&1; systemctl is-active --quiet fail2ban && ok "fail2ban active" || warnx "fail2ban installed but not running"
  else warnx "fail2ban not available"; fi
fi

# 5) keep the runtime secret file out of git status so `melorin` updates and ops-watch drift checks stay quiet.
if [ -d .git ] && ! git check-ignore -q secrets/metrics-token 2>/dev/null; then
  mkdir -p .git/info; grep -qx 'secrets/metrics-token' .git/info/exclude 2>/dev/null || echo 'secrets/metrics-token' >> .git/info/exclude
fi

# 5b) Redis needs vm.overcommit_memory=1 (its startup log warns that background saves can fail otherwise).
if [ "$(cat /proc/sys/vm/overcommit_memory 2>/dev/null)" = "1" ]; then ok "vm.overcommit_memory already 1"
else
  sysctl -w vm.overcommit_memory=1 >/dev/null 2>&1 && echo 'vm.overcommit_memory=1' > /etc/sysctl.d/99-melorin-redis.conf \
    && ok "vm.overcommit_memory=1 (Redis background saves)" || warnx "could not set vm.overcommit_memory=1"
fi

say "Post-install: verification"
tls_diagnose() { # $1 = domain: say WHY https is not answering (rate limit, DNS, validation) instead of a generic hint
  local logs line; logs="$(docker logs --tail 300 "$(docker ps -qf name=caddy | head -1)" 2>&1 || true)"
  line="$(printf '%s\n' "$logs" | grep -F "$1" | grep -E 'rateLimited' | tail -1)"
  if [ -n "$line" ]; then
    warnx "$1: Let's Encrypt rate limit (5 certificates / 7 days for this exact hostname set), $(printf '%s' "$line" | sed -n 's/.*retry after \([0-9: -]* UTC\).*/retry after \1/p'). Caddy retries by itself once the limit expires (ZeroSSL is only a fallback where it accepts the domain; it refuses .ir). Do not reinstall in the meantime: every reinstall must reuse the existing certificate volume."
  elif printf '%s\n' "$logs" | grep -F "$1" | grep -qiE 'Timeout during connect|no valid A records|Connection refused|firewall'; then
    warnx "$1: the CA could not reach this server on port 80: check DNS and the cloud firewall (80/443)"
  elif printf '%s\n' "$logs" | grep -F "$1" | grep -qiE 'error'; then
    warnx "$1: certificate issuance reports an error, see: docker logs $(docker ps -qf name=caddy | head -1) | grep -i error"
  fi
}
for k in MELORIN_DOMAIN MELORIN_ADMIN_DOMAIN; do
  d="$(env_get $k)"; [ -z "$d" ] && continue
  code=""; for _ in $(seq 1 12); do code="$(curl -sS -m 10 -o /dev/null -w '%{http_code}' "https://$d/" 2>/dev/null || true)"; [ "$code" = 200 ] && break; sleep 5; done
  if [ "$code" = 200 ]; then ok "https://$d answers 200 (TLS valid)"
  else warnx "https://$d did not answer 200 (got '${code:-none}')"; tls_diagnose "$d"; fi
done
tok="$(env_get MELORIN_TELEGRAM_TOKEN)"
if [ -n "$tok" ]; then
  curl -fsS -m 10 "https://api.telegram.org/bot${tok}/getMe" >/dev/null 2>&1 && ok "Telegram bot token valid" || warnx "Telegram bot token could not be verified"
else warnx "no Telegram bot token set"; fi
bad="$(docker ps --format '{{.Names}} {{.Status}}' | grep -vE '\((healthy|health: starting)\)' || true)"
[ -z "$bad" ] && ok "all containers healthy" || warnx "containers not healthy: $bad"
[ -s secrets/backup/age-identity.txt ] && warnx "copy $APP_DIR/secrets/backup/age-identity.txt OFF this server (only key that decrypts backups)"
echo
[ "$WARNS" -eq 0 ] && say "post-install: all good" || say "post-install: $WARNS item(s) need attention (see above)"
exit 0
