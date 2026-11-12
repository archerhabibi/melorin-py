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

# Persian message template; times are shown in Iran time (UTC+3:30, no DST since 2022) via a fixed 3h30m Duration (alerts.yml carries summary_fa / hint_fa for every rule; falls back to the English summary).
cat > /tmp/telegram.tmpl <<'TMPL'
{{ define "melorin.telegram" -}}
{{ if eq .Status "firing" }}🚨 هشدار ملورین ({{ .Alerts.Firing | len }} مورد فعال){{ else }}✅ هشدار برطرف شد{{ end }}
{{ range .Alerts }}
{{ if eq .Status "resolved" }}✅ برطرف شد{{ else if eq .Labels.severity "critical" }}🔴 بحرانی{{ else }}🟠 هشدار{{ end }}
{{ or .Annotations.summary_fa .Annotations.summary }}
{{- with .Labels.panel }}
پنل: {{ . }}{{ end }}
{{- with .Labels.server }}
سرور: {{ . }}{{ end }}
{{- with .Labels.job }}{{ if ne . "melorin-api" }}
کار: {{ . }}{{ end }}{{ end }}
{{- if eq .Status "firing" }}{{ with .Annotations.hint_fa }}
💡 {{ . }}{{ end }}{{ end }}
🕒 شروع: {{ (.StartsAt.Add 12600000000000).Format "2006-01-02 15:04" }} (وقت تهران)
{{- if eq .Status "resolved" }}
🕒 پایان: {{ (.EndsAt.Add 12600000000000).Format "2006-01-02 15:04" }} (وقت تهران){{ end }}
{{ end -}}
{{- end }}
TMPL
{
  echo "global:"
  echo "  resolve_timeout: 5m"
  if [ "$mail" = 1 ]; then
    echo "  smtp_smarthost: '$(yq "${ALERT_SMTP_HOST}")'"
    echo "  smtp_from: '$(yq "${ALERT_SMTP_FROM}")'"
    [ -n "${ALERT_SMTP_USER:-}" ] && echo "  smtp_auth_username: '$(yq "${ALERT_SMTP_USER}")'"
    [ -n "${ALERT_SMTP_PASSWORD:-}" ] && echo "  smtp_auth_password: '$(yq "${ALERT_SMTP_PASSWORD}")'"
  fi
  echo "templates: ['/tmp/telegram.tmpl']"
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
    echo "        message: '{{ template \"melorin.telegram\" . }}'"
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
