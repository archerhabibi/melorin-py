#!/usr/bin/env bash
set -euo pipefail

# PG-16: encrypted backup of the PasarGuard PANEL (its database and its data directory), same protocol as backup_secure.sh:
# no password in argv, age-encrypted artifact, checksum, retention, optional off-site copy (exit 3 = local OK, off-site failed).
#
#   MELORIN_PANEL_BACKUP_DATABASE_URL  postgresql://user:pass@host:port/db  - the panel's database. Use the DATABASE port, not PgBouncer
#                                      in transaction mode (pg_dump needs a real session). Optional if only files are backed up.
#   MELORIN_PANEL_BACKUP_PATHS         colon-separated directories to archive, e.g. /var/lib/pasarguard (certs, node CA, env). Optional.
# At least one of the two is required. The artifact is  panel-<UTC stamp>.tar.age  holding panel-db.dump and/or panel-data.tar.
if [[ -z "${MELORIN_PANEL_BACKUP_DATABASE_URL:-}" && -z "${MELORIN_PANEL_BACKUP_PATHS:-}" ]]; then
  echo "panel backup is not configured (set MELORIN_PANEL_BACKUP_DATABASE_URL and/or MELORIN_PANEL_BACKUP_PATHS)" >&2
  exit 2
fi
: "${MELORIN_BACKUP_DIR:=./var/backups}"
: "${MELORIN_BACKUP_RETENTION_DAYS:=30}"
: "${MELORIN_BACKUP_RECIPIENT_FILE:?MELORIN_BACKUP_RECIPIENT_FILE is required}"
[[ -s "$MELORIN_BACKUP_RECIPIENT_FILE" ]] || { echo "backup recipient file is empty" >&2; exit 2; }
mkdir -p "$MELORIN_BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
stage="$(mktemp -d)"
pgpass="$stage/.pgpass"
raw="$MELORIN_BACKUP_DIR/panel-$stamp.tar"
out="$raw.age"
trap 'rm -rf "$stage" "$raw"' EXIT
umask 077

if [[ -n "${MELORIN_PANEL_BACKUP_DATABASE_URL:-}" ]]; then
  mapfile -t DB_PARTS < <(python3 - "$MELORIN_PANEL_BACKUP_DATABASE_URL" "$pgpass" <<'PY'
import sys
from urllib.parse import unquote, urlparse
u = urlparse(sys.argv[1])
if u.scheme not in {"postgresql", "postgresql+asyncpg", "postgres"} or not all((u.hostname, u.username, u.path.lstrip("/"))):
    raise SystemExit("MELORIN_PANEL_BACKUP_DATABASE_URL must be a complete PostgreSQL URL")
def esc(value):
    return str(value).replace("\\", "\\\\").replace(":", "\\:")
open(sys.argv[2], "w").write(":".join(esc(x) for x in (u.hostname, u.port or 5432, u.path.lstrip("/"), unquote(u.username), unquote(u.password or ""))) + "\n")
print(u.hostname); print(u.port or 5432); print(u.path.lstrip("/")); print(unquote(u.username))
PY
)
  chmod 600 "$pgpass"
  PGHOST="${DB_PARTS[0]}" PGPORT="${DB_PARTS[1]}" PGDATABASE="${DB_PARTS[2]}" PGUSER="${DB_PARTS[3]}" PGPASSFILE="$pgpass" \
    pg_dump --format=custom --no-owner --file="$stage/panel-db.dump"
  rm -f "$pgpass"
fi

if [[ -n "${MELORIN_PANEL_BACKUP_PATHS:-}" ]]; then
  IFS=':' read -r -a paths <<< "$MELORIN_PANEL_BACKUP_PATHS"
  existing=()
  for p in "${paths[@]}"; do
    [[ -z "$p" ]] && continue
    [[ -e "$p" ]] || { echo "panel backup path does not exist: $p" >&2; exit 1; }
    existing+=("$p")
  done
  [[ "${#existing[@]}" -gt 0 ]] || { echo "MELORIN_PANEL_BACKUP_PATHS lists no path" >&2; exit 2; }
  tar --create --file="$stage/panel-data.tar" --absolute-names --warning=no-file-changed "${existing[@]}"
fi

members=()
for m in panel-db.dump panel-data.tar; do [[ -f "$stage/$m" ]] && members+=("$m"); done
tar --create --file="$raw" --directory="$stage" "${members[@]}"
age --encrypt --recipients-file "$MELORIN_BACKUP_RECIPIENT_FILE" --output "$out" "$raw"
sha256sum "$out" > "$out.sha256"
sha256sum --check "$out.sha256"
find "$MELORIN_BACKUP_DIR" -type f \( -name 'panel-*.tar.age' -o -name 'panel-*.tar.age.sha256' \) -mtime +"$MELORIN_BACKUP_RETENTION_DAYS" -delete
offsite_rc=0
if [[ -n "${MELORIN_BACKUP_OFFSITE_URI:-}" ]]; then
  rclone copy "$out" "$MELORIN_BACKUP_OFFSITE_URI" && rclone copy "$out.sha256" "$MELORIN_BACKUP_OFFSITE_URI" || offsite_rc=$?
fi
echo "$out"
if [[ "$offsite_rc" -ne 0 ]]; then
  echo "off-site copy failed (rclone exit $offsite_rc); local panel backup kept at $out" >&2
  exit 3
fi
