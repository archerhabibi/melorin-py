#!/usr/bin/env bash
set -euo pipefail

# I34: external integration smoke gate. Never substitutes mocks for real
# dependencies. Every selected integration must be explicitly configured.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${MELORIN_DATABASE_URL:?Set MELORIN_DATABASE_URL to a PostgreSQL URL}"
: "${MELORIN_REDIS_URL:?Set MELORIN_REDIS_URL}"

case "$MELORIN_DATABASE_URL" in
  postgresql+asyncpg://*|postgresql://*) ;;
  *) echo "MELORIN_DATABASE_URL must use PostgreSQL" >&2; exit 2 ;;
esac

python scripts/preflight.py --runtime
(cd apps/api && alembic upgrade head)
(cd apps/api && python ../../scripts/verify_runtime.py)

if [[ "${MELORIN_RUN_COMPOSE:-0}" == "1" ]]; then
  command -v docker >/dev/null
  docker compose config >/dev/null
  docker compose up -d --build
  trap 'docker compose down' EXIT
  for service in api worker store_web admin_web caddy alertmanager prometheus; do
    docker compose ps --status running "$service" | grep -q "$service" || { echo "$service is not running" >&2; exit 1; }
  done
  curl --fail --silent --show-error http://localhost/health/live >/dev/null
  curl --fail --silent --show-error http://localhost/health/ready >/dev/null
  docker compose exec -T prometheus wget --spider --quiet http://127.0.0.1:9090/-/ready
  if [[ -n "${MELORIN_EXPECT_TELEGRAM_SERVICES:-}" ]]; then
    for service in telegram_main telegram_reseller; do
      docker compose ps --status running "$service" | grep -q "$service" || { echo "$service is not running" >&2; exit 1; }
    done
  fi
fi

if [[ "${MELORIN_RUN_EXTERNAL_PROVIDERS:-0}" == "1" ]]; then
  : "${MELORIN_ZARINPAL_SANDBOX:=0}"
  : "${MELORIN_PANEL_SMOKE_URL:?Set MELORIN_PANEL_SMOKE_URL for provider smoke}"
  curl --fail --silent --show-error --max-time 15 "$MELORIN_PANEL_SMOKE_URL" >/dev/null
fi

if [[ "${MELORIN_RUN_TELEGRAM_SMOKE:-0}" == "1" ]]; then
  : "${MELORIN_TELEGRAM_BOT_TOKEN:?Set MELORIN_TELEGRAM_BOT_TOKEN}"
  curl --fail --silent --show-error --max-time 15 \
    "https://api.telegram.org/bot${MELORIN_TELEGRAM_BOT_TOKEN}/getMe" >/dev/null
  if [[ -n "${MELORIN_TELEGRAM_RESELLER_BOT_TOKEN:-}" ]]; then
    curl --fail --silent --show-error --max-time 15 \
      "https://api.telegram.org/bot${MELORIN_TELEGRAM_RESELLER_BOT_TOKEN}/getMe" >/dev/null
  fi
fi

if [[ "${MELORIN_RUN_PROMETHEUS_SMOKE:-0}" == "1" ]]; then
  : "${MELORIN_PROMETHEUS_URL:?Set MELORIN_PROMETHEUS_URL}"
  curl --fail --silent --show-error --max-time 15 "${MELORIN_PROMETHEUS_URL%/}/-/ready" >/dev/null
fi

echo "I34 integration smoke gate passed for configured checks"
