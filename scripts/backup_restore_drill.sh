#!/usr/bin/env bash
set -euo pipefail

# I41: destructive only to a uniquely named temporary database.
: "${BACKUP_ARCHIVE:?BACKUP_ARCHIVE is required}"
: "${BACKUP_IDENTITY_FILE:?BACKUP_IDENTITY_FILE is required}"
: "${MELORIN_DATABASE_URL:?MELORIN_DATABASE_URL is required}"
: "${RESTORE_DRILL_DIR:=./var/restore-drill}"
: "${MELORIN_RPO_HOURS:=24}"
: "${MELORIN_RTO_HOURS:=8}"

command -v age >/dev/null
command -v pg_restore >/dev/null
command -v createdb >/dev/null
command -v dropdb >/dev/null
mkdir -p "$RESTORE_DRILL_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
raw="$RESTORE_DRILL_DIR/restore-$stamp.dump"
db_name="melorin_restore_drill_${stamp//[^0-9A-Za-z]/}"
trap 'rm -f "$raw"; dropdb --if-exists "$db_name" >/dev/null 2>&1 || true' EXIT

sha256sum --check "${BACKUP_CHECKSUM_FILE:-$BACKUP_ARCHIVE.sha256}"
age --decrypt --identity "$BACKUP_IDENTITY_FILE" --output "$raw" "$BACKUP_ARCHIVE"

mapfile -t DB_PARTS < <(python - "$MELORIN_DATABASE_URL" <<'PY'
import sys
from urllib.parse import urlparse
u = urlparse(sys.argv[1])
if u.scheme not in {"postgresql", "postgresql+asyncpg", "postgres"} or not u.hostname or not u.username:
    raise SystemExit("MELORIN_DATABASE_URL must be a PostgreSQL URL")
print(u.hostname); print(u.port or 5432); print(u.username); print(u.password or "")
PY
)
export PGHOST="${DB_PARTS[0]}" PGPORT="${DB_PARTS[1]}" PGUSER="${DB_PARTS[2]}" PGPASSWORD="${DB_PARTS[3]}"
createdb "$db_name"
PGDATABASE="$db_name" pg_restore --no-owner --exit-on-error --dbname="$db_name" "$raw"
tables="$(psql --dbname="$db_name" -Atc "select count(*) from pg_catalog.pg_tables where schemaname='public'")"
[[ "$tables" -gt 0 ]] || { echo "restore drill produced no public tables" >&2; exit 1; }
echo "I41 restore drill passed: database=$db_name tables=$tables rpo_hours=$MELORIN_RPO_HOURS rto_hours=$MELORIN_RTO_HOURS"
