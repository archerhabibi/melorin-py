#!/usr/bin/env bash
set -euo pipefail

# H012: one local/CI entrypoint for the complete declared quality gate.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python scripts/verify_runtime.py
bash scripts/check_secrets.sh
python scripts/check_frontend_contracts.py
python scripts/check_release_matrix.py
# M6.11: static guards must run in the same gate that CI runs.
python scripts/check_g001_g010.py
python scripts/check_quality_config.py
python scripts/check_ops_p0.py
bash scripts/test_deploy.sh
python -m compileall -q apps/api/melorin apps/api/tests apps/telegram-main apps/telegram-reseller
ruff check apps/api/melorin --config apps/api/pyproject.toml
ruff format --check apps/api/melorin apps/api/tests --config apps/api/pyproject.toml
for web in apps/store-web apps/admin-web; do
  (cd "$web" && npm audit --include=dev --audit-level=high)
done
python scripts/test_matrix.py unit
echo "Melorin quality gate passed"
