#!/usr/bin/env bash
set -euo pipefail

# F007/F008: no password in argv, encrypted artifact, checksum, retention, optional offsite copy.
: "${MELORIN_DATABASE_URL:?MELORIN_DATABASE_URL is required}"
: "${MELORIN_BACKUP_DIR:=./var/backups}"
: "${MELORIN_BACKUP_RETENTION_DAYS:=30}"
: "${MELORIN_BACKUP_RECIPIENT_FILE:?MELORIN_BACKUP_RECIPIENT_FILE is required}"
BACKUP_DIR="$MELORIN_BACKUP_DIR"
[[ -s "$MELORIN_BACKUP_RECIPIENT_FILE" ]] || { echo "backup recipient file is empty" >&2; exit 2; }
mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
raw="$BACKUP_DIR/melorin-$stamp.dump"
out="$raw.age"
pgurl="$MELORIN_DATABASE_URL"
pgpass="$(mktemp)"
trap 'rm -f "$pgpass" "$raw"' EXIT
mapfile -t DB_PARTS < <(python - "$pgurl" "$pgpass" <<'PY'
import sys
from urllib.parse import urlparse
u=urlparse(sys.argv[1])
if u.scheme not in {"postgresql", "postgresql+asyncpg", "postgres"} or not all((u.hostname, u.username, u.password, u.path.lstrip("/"))):
    raise SystemExit("MELORIN_DATABASE_URL must be a complete PostgreSQL URL")
def esc(value):
    return str(value).replace("\\", "\\\\").replace(":", "\\:")
open(sys.argv[2],"w").write(":".join(esc(x) for x in (u.hostname, u.port or 5432, u.path.lstrip("/"), u.username, u.password)) + "\n")
print(u.hostname)
print(u.port or 5432)
print(u.path.lstrip("/"))
print(u.username)
PY
)
chmod 600 "$pgpass"
PGHOST="${DB_PARTS[0]}" PGPORT="${DB_PARTS[1]}" PGDATABASE="${DB_PARTS[2]}" PGUSER="${DB_PARTS[3]}" PGPASSFILE="$pgpass" \
  pg_dump --format=custom --no-owner --file="$raw"
age --encrypt --recipients-file "$MELORIN_BACKUP_RECIPIENT_FILE" --output "$out" "$raw"
sha256sum "$out" > "$out.sha256"
sha256sum --check "$out.sha256"
find "$MELORIN_BACKUP_DIR" -type f -mtime +"$MELORIN_BACKUP_RETENTION_DAYS" -delete
if [[ -n "${MELORIN_BACKUP_OFFSITE_URI:-}" ]]; then
  rclone copy "$out" "$MELORIN_BACKUP_OFFSITE_URI"
  rclone copy "$out.sha256" "$MELORIN_BACKUP_OFFSITE_URI"
fi
echo "$out"
