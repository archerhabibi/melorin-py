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

work_dir="$(mktemp -d "$RESTORE_DRILL_DIR/restore-XXXXXXXXXXXX")"
suffix="${work_dir##*/}"
db_name="melorin_restore_drill_${suffix#restore-}"
raw="$work_dir/backup.dump"
db_created=0
cleanup() {
  local failed=0
  if [[ "$db_created" == 1 ]] && ! dropdb --if-exists "$db_name" >/dev/null; then
    echo "restore drill: failed to drop temporary database $db_name" >&2
    failed=1
  fi
  if ! rm -f -- "$raw"; then
    echo "restore drill: failed to remove temporary dump $raw" >&2
    failed=1
  fi
  if ! rmdir -- "$work_dir"; then
    echo "restore drill: failed to remove temporary directory $work_dir" >&2
    failed=1
  fi
  return "$failed"
}
trap 'cleanup || true' EXIT

# V-027: checksum files carry the archive BASENAME, so verify from the archive's own directory (works off the original host).
_ck="${BACKUP_CHECKSUM_FILE:-$BACKUP_ARCHIVE.sha256}"
( cd "$(dirname "$BACKUP_ARCHIVE")" && sha256sum --check "$(realpath --relative-to="$(dirname "$BACKUP_ARCHIVE")" "$_ck" 2>/dev/null || echo "$_ck")" )
age --decrypt --identity "$BACKUP_IDENTITY_FILE" --output "$raw" "$BACKUP_ARCHIVE"

mapfile -t DB_PARTS < <(python3 - "$MELORIN_DATABASE_URL" <<'PY'
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
db_created=1
PGDATABASE="$db_name" pg_restore --no-owner --exit-on-error --dbname="$db_name" "$raw"
tables="$(psql --dbname="$db_name" -Atc "select count(*) from pg_catalog.pg_tables where schemaname='public'")"
[[ "$tables" -gt 0 ]] || { echo "restore drill produced no public tables" >&2; exit 1; }
# V-027: "tables > 0" proves little. The restored copy must carry an alembic revision, hold at least one user, and its revision
# must match the live database when that one is reachable (a backup from a different schema is useless for a restore).
rev="$(psql --dbname="$db_name" -Atc "select version_num from alembic_version limit 1" 2>/dev/null || true)"
[[ -n "$rev" ]] || { echo "restore drill: alembic_version is empty or missing" >&2; exit 1; }
users="$(psql --dbname="$db_name" -Atc "select count(*) from users" 2>/dev/null || echo 0)"
[[ "$users" -gt 0 ]] || { echo "restore drill: restored users table is empty" >&2; exit 1; }
live_db="$(python3 - "$MELORIN_DATABASE_URL" <<'PY2'
import sys
from urllib.parse import urlparse
print(urlparse(sys.argv[1]).path.lstrip("/"))
PY2
)"
live_rev="$(PGDATABASE="$live_db" psql -Atc "select version_num from alembic_version limit 1" 2>/dev/null || true)"
if [[ -n "$live_rev" && "$live_rev" != "$rev" ]]; then
  echo "restore drill: backup schema revision $rev differs from live $live_rev" >&2; exit 1
fi
trap - EXIT
cleanup
echo "I41 restore drill passed: database=$db_name tables=$tables users=$users alembic=$rev rpo_hours=$MELORIN_RPO_HOURS rto_hours=$MELORIN_RTO_HOURS"
