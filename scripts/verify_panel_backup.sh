#!/usr/bin/env bash
set -euo pipefail

# PG-16: NON-destructive restore test of a panel backup. Proves the artifact is intact and readable; it restores nothing and touches no
# database. Run it after every change to the backup setup and at least monthly (docs/RUNBOOK.md, "Panel backup and recovery").
#
#   BACKUP_ARCHIVE        path to panel-<stamp>.tar.age
#   BACKUP_IDENTITY_FILE  the age PRIVATE key (kept offline, NOT on the server that makes the backups)
#   PG_RESTORE            optional: the pg_restore command to use (default: pg_restore). It must be at least as new as the
#                         PostgreSQL that made the dump (the panel runs PG 17; Ubuntu 24.04 ships pg_restore 16). The dump is
#                         read from stdin, so a container works too, e.g.
#                         PG_RESTORE='docker exec -i pasarguard-timescaledb-1 pg_restore'
: "${BACKUP_ARCHIVE:?BACKUP_ARCHIVE is required}"
: "${BACKUP_IDENTITY_FILE:?BACKUP_IDENTITY_FILE is required}"
command -v age >/dev/null
read -r -a pg_restore_cmd <<<"${PG_RESTORE:-pg_restore}"
command -v "${pg_restore_cmd[0]}" >/dev/null
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
umask 077

sha256sum --check "${BACKUP_CHECKSUM_FILE:-$BACKUP_ARCHIVE.sha256}"
age --decrypt --identity "$BACKUP_IDENTITY_FILE" --output "$work/panel.tar" "$BACKUP_ARCHIVE"
members="$(tar --list --file="$work/panel.tar")"
[[ -n "$members" ]] || { echo "panel backup is empty" >&2; exit 1; }
found=0
if grep -qx 'panel-db.dump' <<<"$members"; then
  tar --extract --file="$work/panel.tar" --directory="$work" panel-db.dump
  if ! listing="$("${pg_restore_cmd[@]}" --list <"$work/panel-db.dump" 2>"$work/pg_restore.err")"; then
    cat "$work/pg_restore.err" >&2
    echo "pg_restore could not read the dump; if it says 'unsupported version', use a pg_restore as new as the panel's PostgreSQL (PG_RESTORE=...)" >&2
    exit 1
  fi
  entries="$(grep -vc '^;' <<<"$listing" || true)"
  [[ "$entries" -gt 0 ]] || { echo "panel database dump has no objects" >&2; exit 1; }
  echo "database dump readable: $entries objects"
  found=1
fi
if grep -qx 'panel-data.tar' <<<"$members"; then
  tar --extract --file="$work/panel.tar" --directory="$work" panel-data.tar
  files="$(tar --list --file="$work/panel-data.tar" | wc -l)"
  [[ "$files" -gt 0 ]] || { echo "panel data archive is empty" >&2; exit 1; }
  echo "data archive readable: $files entries"
  found=1
fi
[[ "$found" -eq 1 ]] || { echo "panel backup holds neither a database dump nor a data archive" >&2; exit 1; }
echo "panel backup verification passed: $(basename "$BACKUP_ARCHIVE")"
