#!/bin/sh
# Renders /tmp/alertmanager.yml from environment (Alertmanager does not expand env vars itself) and starts it.
# Receivers (any combination):
#   Telegram: ALERT_TELEGRAM_BOT_TOKEN + ALERT_TELEGRAM_CHAT_ID
#   E-mail:   ALERT_SMTP_HOST (host:port) + ALERT_SMTP_FROM + ALERT_EMAIL_TO [+ ALERT_SMTP_USER / ALERT_SMTP_PASSWORD]
# With no receiver configured it still starts (so the stack boots) but logs a loud warning; scripts/deploy.sh warns too.
set -eu
OUT=/tmp/alertmanager.yml
# YAML single-quoted scalar: a literal ' is written as '' (SMTP passwords may contain quotes).
yq() { printf '%s' "$1" | sed "s/'/''/g"; }
tg=0; mail=0
[ -n "${ALERT_TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${ALERT_TELEGRAM_CHAT_ID:-}" ] && tg=1
[ -n "${ALERT_SMTP_HOST:-}" ] && [ -n "${ALERT_SMTP_FROM:-}" ] && [ -n "${ALERT_EMAIL_TO:-}" ] && mail=1

{
  echo "global:"
  echo "  resolve_timeout: 5m"
  if [ "$mail" = 1 ]; then
    echo "  smtp_smarthost: '$(yq "${ALERT_SMTP_HOST}")'"
    echo "  smtp_from: '$(yq "${ALERT_SMTP_FROM}")'"
    [ -n "${ALERT_SMTP_USER:-}" ] && echo "  smtp_auth_username: '$(yq "${ALERT_SMTP_USER}")'"
    [ -n "${ALERT_SMTP_PASSWORD:-}" ] && echo "  smtp_auth_password: '$(yq "${ALERT_SMTP_PASSWORD}")'"
  fi
  echo "route:"
  echo "  receiver: melorin"
  echo "  group_by: [alertname]"
  echo "  group_wait: 30s"
  echo "  group_interval: 5m"
  echo "  repeat_interval: 4h"
  echo "receivers:"
  echo "  - name: melorin"
  if [ "$tg" = 1 ]; then
    echo "    telegram_configs:"
    echo "      - bot_token: '$(yq "${ALERT_TELEGRAM_BOT_TOKEN}")'"
    echo "        chat_id: ${ALERT_TELEGRAM_CHAT_ID}"
    echo "        send_resolved: true"
    echo "        parse_mode: ''"
  fi
  if [ "$mail" = 1 ]; then
    echo "    email_configs:"
    echo "      - to: '$(yq "${ALERT_EMAIL_TO}")'"
    echo "        send_resolved: true"
  fi
} > "$OUT"
chmod 600 "$OUT"

if [ "$tg" = 0 ] && [ "$mail" = 0 ]; then
  echo "WARNING: no alert receiver configured (set ALERT_TELEGRAM_BOT_TOKEN+ALERT_TELEGRAM_CHAT_ID or ALERT_SMTP_*/ALERT_EMAIL_TO in .env). Alerts will NOT be delivered." >&2
fi
exec /bin/alertmanager --config.file="$OUT" --storage.path=/alertmanager --web.listen-address=:9093
