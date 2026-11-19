#!/usr/bin/env bash
# Out-of-stack watchdog (audit V-006). Prometheus/Alertmanager live INSIDE the stack, so they go blind exactly when the API,
# Redis or the whole host dies, and they never saw the main Telegram bot or host resources at all. This script runs from
# cron on the HOST every 5 minutes and talks to Telegram directly (ALERT_TELEGRAM_BOT_TOKEN / ALERT_TELEGRAM_CHAT_ID from .env).
#
# Checks: disk (/ and the Docker data root), available memory, every Compose service (not running, or unhealthy for longer than
# HOST_WATCH_GRACE_MIN), and TLS certificate expiry of the store/admin domains.
# A problem is announced once, repeated every HOST_WATCH_REPEAT_H hours while it lasts, and announced again as resolved.
#
# Test/dry-run knobs: HOST_WATCH_DRY_RUN=1 prints messages instead of sending; HOST_WATCH_STATE_DIR; HOST_WATCH_NOW (epoch).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

DISK_PCT="${HOST_WATCH_DISK_PCT:-88}"          # alert when a filesystem is fuller than this
MEM_MIN_PCT="${HOST_WATCH_MEM_MIN_PCT:-8}"      # alert when MemAvailable is below this percentage of MemTotal
GRACE_MIN="${HOST_WATCH_GRACE_MIN:-10}"         # a service may be down/unhealthy this long before we speak up
CERT_DAYS="${HOST_WATCH_CERT_DAYS:-14}"
REPEAT_H="${HOST_WATCH_REPEAT_H:-6}"
ST="${HOST_WATCH_STATE_DIR:-var/.host-watch}"
NOW="${HOST_WATCH_NOW:-$(date +%s)}"
mkdir -p "$ST" && chmod 700 "$ST" 2>/dev/null || true
exec 9>"$ST/lock"; flock -n 9 || exit 0

env_get() { # value of KEY in .env, without sourcing the file
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed "s/^['\"]//; s/['\"]$//"
}
TOKEN="${ALERT_TELEGRAM_BOT_TOKEN:-$(env_get ALERT_TELEGRAM_BOT_TOKEN)}"
CHAT="${ALERT_TELEGRAM_CHAT_ID:-$(env_get ALERT_TELEGRAM_CHAT_ID)}"

send() { # send TEXT
  if [ "${HOST_WATCH_DRY_RUN:-0}" = 1 ]; then echo "SEND: $1"; return 0; fi
  logger -t melorin-host-watch -- "$1" 2>/dev/null || true
  [ -n "$TOKEN" ] && [ -n "$CHAT" ] || return 0
  curl -fsS -m 15 -o /dev/null "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT}" --data-urlencode "text=$1" >/dev/null 2>&1 || true
}

# problem KEY FIRING_TEXT: record that KEY is currently bad. Spoken on first sight and every REPEAT_H hours.
declare -A BAD=()
problem() { BAD["$1"]="$2"; }

# ---- 1. disk ----------------------------------------------------------------------------------------------------------
for path in / "$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"; do
  [ -n "$path" ] && [ -d "$path" ] || continue
  pct=$(df -P "$path" 2>/dev/null | awk 'NR==2{gsub("%","",$5); print $5}')
  [ -n "${pct:-}" ] && [ "$pct" -ge "$DISK_PCT" ] && problem "disk:$path" "💾 دیسک سرور $path به ${pct}٪ پر شده (آستانه ${DISK_PCT}٪). بکاپ و دیتابیس در خطرند."
done

# ---- 2. memory --------------------------------------------------------------------------------------------------------
if [ -r /proc/meminfo ]; then
  total=$(awk '/^MemTotal:/{print $2}' /proc/meminfo); avail=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
  if [ -n "${total:-}" ] && [ "${total:-0}" -gt 0 ]; then
    apct=$(( avail * 100 / total ))
    [ "$apct" -lt "$MEM_MIN_PCT" ] && problem "mem" "🧠 حافظهٔ آزاد سرور فقط ${apct}٪ است (آستانه ${MEM_MIN_PCT}٪)؛ خطر OOM."
  fi
fi

# ---- 3. compose services (api, worker, telegram-main, reseller bots, db, redis, ...) -----------------------------------
if command -v docker >/dev/null 2>&1; then
  while read -r svc state health since; do
    [ -n "$svc" ] || continue
    case "$svc" in migrate|secrets_init|backup) continue ;; esac   # one-shot / scheduled jobs: a clean exit is normal
    bad=""
    [ "$state" != "running" ] && bad="متوقف است ($state)"
    [ "$state" = "running" ] && [ "$health" = "unhealthy" ] && bad="ناسالم است (unhealthy)"
    if [ -n "$bad" ]; then
      first=$(cat "$ST/since.$svc" 2>/dev/null || true)
      [ -n "$first" ] || { first="$NOW"; echo "$first" > "$ST/since.$svc"; }
      [ $(( (NOW - first) / 60 )) -ge "$GRACE_MIN" ] && problem "svc:$svc" "🔴 سرویس «$svc» بیش از ${GRACE_MIN} دقیقه $bad."
    else
      rm -f "$ST/since.$svc"
    fi
  done < <(docker ps -a --filter label=com.docker.compose.project=melorin -q 2>/dev/null | while read -r id; do
    docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}} {{.State.Status}} {{with .State.Health}}{{.Status}}{{else}}none{{end}} -' "$id" 2>/dev/null
  done)
fi

# ---- 4. TLS expiry ----------------------------------------------------------------------------------------------------
if command -v openssl >/dev/null 2>&1; then
  for key in MELORIN_DOMAIN MELORIN_ADMIN_DOMAIN; do
    d="${!key:-$(env_get "$key")}"
    case "$d" in ""|localhost|*.localhost|*.test|*.local) continue ;; esac
    end=$(echo | timeout 10 openssl s_client -servername "$d" -connect "$d:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    [ -n "$end" ] || continue
    left=$(( ( $(date -d "$end" +%s 2>/dev/null || echo "$NOW") - NOW ) / 86400 ))
    [ "$left" -lt "$CERT_DAYS" ] && problem "cert:$d" "🔐 گواهی TLS دامنهٔ $d تا ${left} روز دیگر منقضی می‌شود."
  done
fi

# ---- announce / repeat / resolve --------------------------------------------------------------------------------------
for key in "${!BAD[@]}"; do
  f="$ST/alert.${key//[^A-Za-z0-9._-]/_}"
  last=$(cat "$f" 2>/dev/null || echo 0)
  if [ $(( (NOW - last) / 3600 )) -ge "$REPEAT_H" ]; then
    send "🚨 ملورین — ${BAD[$key]}"
    echo "$NOW" > "$f"
  fi
done
for f in "$ST"/alert.*; do
  [ -e "$f" ] || continue
  name="${f##*/alert.}"
  still=0
  for key in "${!BAD[@]}"; do [ "${key//[^A-Za-z0-9._-]/_}" = "$name" ] && still=1; done
  if [ "$still" = 0 ]; then send "✅ ملورین — مشکل «$name» برطرف شد."; rm -f "$f"; fi
done
exit 0
