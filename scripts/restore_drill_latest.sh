#!/usr/bin/env bash
# Restore drill against the NEWEST encrypted backup (audit P0-5 / T5): proves the backups can actually be restored.
# Run it on a machine that is NOT the production host - the age identity (private key) must live off the server.
#
#   BACKUP_SOURCE=<dir | rclone-remote:path>  BACKUP_IDENTITY_FILE=<age identity>  MELORIN_DATABASE_URL=<scratch postgres url> \
#     scripts/restore_drill_latest.sh
#
# * picks the newest melorin-*.dump.age (+ .sha256) from a directory, or downloads it with rclone when the source is a remote
# * fails when the newest backup is older than MELORIN_RPO_HOURS (default 24) - a silently stopped backup is caught here
# * restores into a uniquely named temporary database (scripts/backup_restore_drill.sh) and drops it afterwards
# * appends one result line to $RESTORE_DRILL_LOG (default var/restore-drill.log); exit 0 only when everything passed
set -euo pipefail
: "${BACKUP_SOURCE:?BACKUP_SOURCE is required (directory or rclone remote:path)}"
: "${BACKUP_IDENTITY_FILE:?BACKUP_IDENTITY_FILE is required}"
: "${MELORIN_DATABASE_URL:?MELORIN_DATABASE_URL (scratch PostgreSQL with CREATEDB rights) is required}"
: "${MELORIN_RPO_HOURS:=24}"
: "${RESTORE_DRILL_LOG:=var/restore-drill.log}"
HERE="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
mkdir -p "$(dirname "$RESTORE_DRILL_LOG")"
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$RESTORE_DRILL_LOG"; }
die() { log "RESTORE DRILL FAILED: $*"; exit 1; }

if [ -d "$BACKUP_SOURCE" ]; then
  newest="$(find "$BACKUP_SOURCE" -maxdepth 1 -type f -name 'melorin-*.dump.age' | sort | tail -n1)"
  [ -n "$newest" ] || die "no melorin-*.dump.age in $BACKUP_SOURCE"
  cp "$newest" "$work/"; cp "$newest.sha256" "$work/" 2>/dev/null || die "checksum file missing next to $newest"
else
  command -v rclone >/dev/null || die "rclone is required for remote sources"
  name="$(rclone lsf --files-only "$BACKUP_SOURCE" | grep -E '^melorin-.*\.dump\.age$' | sort | tail -n1 || true)"
  [ -n "$name" ] || die "no melorin-*.dump.age at $BACKUP_SOURCE"
  rclone copyto "$BACKUP_SOURCE/$name" "$work/$name" && rclone copyto "$BACKUP_SOURCE/$name.sha256" "$work/$name.sha256" \
    || die "download of $name failed"
fi
archive="$(find "$work" -maxdepth 1 -name 'melorin-*.dump.age' | head -n1)"
base="$(basename "$archive")"

# Age comes from the UTC timestamp embedded in the name (melorin-YYYYmmddTHHMMSSZ.dump.age), not from file mtimes.
ts="${base#melorin-}"; ts="${ts%%.dump.age}"
[[ "$ts" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "cannot read the timestamp from $base"
iso="${ts:0:4}-${ts:4:2}-${ts:6:2}T${ts:9:2}:${ts:11:2}:${ts:13:2}Z"
age_h=$(( ( $(date -u +%s) - $(date -u -d "$iso" +%s) ) / 3600 ))
[ "$age_h" -le "$MELORIN_RPO_HOURS" ] || die "newest backup $base is ${age_h}h old (RPO ${MELORIN_RPO_HOURS}h) - are backups still running?"

BACKUP_ARCHIVE="$archive" BACKUP_CHECKSUM_FILE="$archive.sha256" RESTORE_DRILL_DIR="$work/drill" \
  bash "$HERE/backup_restore_drill.sh" >"$work/drill.out" 2>&1 || { tail -n 20 "$work/drill.out" >&2; die "restore of $base failed"; }
log "RESTORE DRILL OK: $base (${age_h}h old) $(tail -n1 "$work/drill.out")"
