#!/usr/bin/env bash
# Generate real, complete package-lock.json files (needs npm registry access). Commit the results.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for app in store-web admin-web; do
  (cd "$ROOT/apps/$app" && rm -f package-lock.json && npm install --package-lock-only --ignore-scripts --no-audit --no-fund)
done
python3 "$ROOT/scripts/check_web_lockfiles.py"
