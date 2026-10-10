#!/usr/bin/env bash
set -euo pipefail

# J06: one explicit staging run. This script never converts missing credentials
# into a pass and writes timestamped evidence suitable for the release matrix.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
EVIDENCE_DIR="${J06_EVIDENCE_DIR:-./var/evidence/j06-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$EVIDENCE_DIR"

required=(POSTGRES_PASSWORD MELORIN_DATABASE_URL MELORIN_REDIS_URL MELORIN_JWT_SECRET)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || { echo "missing $name" >&2; exit 2; }
done

{
  echo "J06 staging evidence"
  date -u --iso-8601=seconds
  git rev-parse HEAD 2>/dev/null || echo "git_commit=unavailable"
  echo "compose=$(docker compose version)"
} | tee "$EVIDENCE_DIR/metadata.txt"

bash scripts/integration_smoke.sh 2>&1 | tee "$EVIDENCE_DIR/integration-smoke.log"
docker compose ps > "$EVIDENCE_DIR/compose-ps.txt"
docker compose logs --no-color --tail=200 > "$EVIDENCE_DIR/compose-log-tail.txt"

if [[ "${MELORIN_RUN_BACKUP_DRILL:-0}" == "1" ]]; then
  bash scripts/backup_restore_verify.sh 2>&1 | tee "$EVIDENCE_DIR/backup-verify.log"
  bash scripts/backup_restore_drill.sh 2>&1 | tee "$EVIDENCE_DIR/backup-restore-drill.log"
fi

echo "J06 evidence bundle written to $EVIDENCE_DIR"
