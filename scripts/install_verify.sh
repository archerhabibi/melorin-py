#!/usr/bin/env bash
set -euo pipefail

# H001: reproducible local installation and fail-fast verification.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
VENV="${VENV:-$ROOT/.venv}"
"$PYTHON" "$ROOT/scripts/preflight.py"

"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install --require-hashes -r "$ROOT/apps/api/requirements-dev.txt"
"$VENV/bin/python" "$ROOT/scripts/verify_runtime.py"
"$VENV/bin/python" -m compileall -q "$ROOT/apps/api/melorin" "$ROOT/apps/api/tests"
"$VENV/bin/python" "$ROOT/scripts/check_release_matrix.py"
"$VENV/bin/python" "$ROOT/scripts/check_frontend_contracts.py"
"$VENV/bin/python" "$ROOT/scripts/check_web_lockfiles.py"
"$VENV/bin/python" -m ruff check "$ROOT/apps/api/melorin" --config "$ROOT/apps/api/pyproject.toml"
"$VENV/bin/python" -m pytest -q "$ROOT/apps/api/tests"
echo "Melorin installation verification passed"
