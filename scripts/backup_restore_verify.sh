#!/usr/bin/env bash
set -euo pipefail

# F008 restore evidence gate: decrypt one artifact and validate its pg_dump archive.
: "${BACKUP_ARCHIVE:?BACKUP_ARCHIVE is required}"
: "${BACKUP_IDENTITY_FILE:?BACKUP_IDENTITY_FILE is required}"
: "${BACKUP_CHECKSUM_FILE:=${BACKUP_ARCHIVE}.sha256}"
: "${RESTORE_VERIFY_DIR:=./var/restore-verify}"
mkdir -p "$RESTORE_VERIFY_DIR"
sha256sum --check "$BACKUP_CHECKSUM_FILE"
raw="$RESTORE_VERIFY_DIR/$(basename "${BACKUP_ARCHIVE%.age}").dump"
trap 'rm -f "$raw"' EXIT
age --decrypt --identity "$BACKUP_IDENTITY_FILE" --output "$raw" "$BACKUP_ARCHIVE"
pg_restore --list "$raw" >/dev/null
echo "restore archive verification passed: $BACKUP_ARCHIVE"
