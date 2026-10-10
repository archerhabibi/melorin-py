#!/usr/bin/env bash
set -euo pipefail
: "${MELORIN_DATABASE_URL:?Set MELORIN_DATABASE_URL}"
: "${MELORIN_JWT_SECRET:?Set MELORIN_JWT_SECRET}"
if [[ "${MELORIN_ENV:-development}" == "production" && "${MELORIN_JWT_SECRET}" == "dev-insecure-change-me" ]]; then echo 'Refusing default JWT secret in production' >&2; exit 1; fi
cd "$(dirname "$0")/../apps/api"
alembic upgrade head
python -m melorin.cli bootstrap
