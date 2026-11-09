#!/usr/bin/env bash
# Audit principle 1 / T47: before every cleanup phase, tag the exact commit and take an encrypted backup.
#   scripts/phase_snapshot.sh P2            # tag only (safe anywhere)
#   scripts/phase_snapshot.sh P2 --backup   # tag + scripts/backup_secure.sh (needs the env that script documents)
set -euo pipefail
phase="${1:?usage: phase_snapshot.sh <phase-name> [--backup]}"
[[ "$phase" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "phase name: letters, digits . _ - only" >&2; exit 2; }
cd "$(dirname "$0")/.."
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "working tree has uncommitted changes: commit or stash first, a tag must name a reproducible state" >&2
  exit 3
fi
tag="pre-${phase}-$(date -u +%Y%m%dT%H%M%SZ)"
git tag -a "$tag" -m "snapshot before audit phase ${phase}"
echo ">> tagged ${tag} at $(git rev-parse --short HEAD) (push with: git push origin ${tag})"
if [[ "${2:-}" == "--backup" ]]; then
  echo ">> encrypted backup"
  bash scripts/backup_secure.sh
fi
