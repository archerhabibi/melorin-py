#!/usr/bin/env bash
# Exercise temporary-resource ownership without requiring PostgreSQL or age.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf -- "$T"' EXIT
mkdir -p "$T/bin" "$T/drills" "$T/log"
printf 'archive' > "$T/backup.age"
(cd "$T" && sha256sum backup.age > backup.age.sha256)

cat > "$T/bin/date" <<'STUB'
#!/usr/bin/env bash
echo 20261125T010101Z
STUB
cat > "$T/bin/age" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
while (($#)); do
  case "$1" in
    --identity) shift 2 ;;
    --output) out="$2"; shift 2 ;;
    --decrypt) shift ;;
    *) archive="$1"; shift ;;
  esac
done
printf '%s\n' "$out" >> "$DRILL_TEST_LOG/raw"
cp -- "$archive" "$out"
STUB
cat > "$T/bin/createdb" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$1" >> "$DRILL_TEST_LOG/created"
[[ "${DRILL_FAIL_CREATE:-0}" != 1 ]]
STUB
cat > "$T/bin/dropdb" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$2" >> "$DRILL_TEST_LOG/dropped"
[[ "${DRILL_FAIL_DROP:-0}" != 1 ]]
STUB
cat > "$T/bin/pg_restore" <<'STUB'
#!/usr/bin/env bash
[[ "${DRILL_FAIL_RESTORE:-0}" != 1 ]]
STUB
cat > "$T/bin/psql" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *pg_catalog.pg_tables*) echo 1 ;;
  *alembic_version*) echo test_revision ;;
  *'count(*) from users'*) echo 1 ;;
  *) exit 1 ;;
esac
STUB
chmod +x "$T/bin/"*
export PATH="$T/bin:$PATH" DRILL_TEST_LOG="$T/log"
export BACKUP_ARCHIVE="$T/backup.age" BACKUP_IDENTITY_FILE="$T/identity"
export MELORIN_DATABASE_URL='postgresql://test:test@127.0.0.1/test' RESTORE_DRILL_DIR="$T/drills"
fail() { echo "FAIL: $*" >&2; exit 1; }
reset_log() { : > "$T/log/created"; : > "$T/log/dropped"; : > "$T/log/raw"; }
assert_clean() {
  [[ -z "$(find "$T/drills" -mindepth 1 -maxdepth 1 ! -name restore-20261125T010101Z.dump -print)" ]] || fail 'temporary files were left behind'
  [[ "$(cat "$T/drills/restore-20261125T010101Z.dump")" == sentinel ]] || fail 'existing dump changed'
}
printf sentinel > "$T/drills/restore-20261125T010101Z.dump"

reset_log
printf 'invalid checksum\n' > "$T/invalid.sha256"
if BACKUP_CHECKSUM_FILE="$T/invalid.sha256" bash "$SRC/scripts/backup_restore_drill.sh" > "$T/out" 2>&1; then
  fail 'invalid checksum was accepted'
fi
[[ ! -s "$T/log/created" && ! -s "$T/log/dropped" ]] || fail 'checksum failure touched a database'
assert_clean
echo 'ok  checksum failure leaves existing resources alone'

reset_log
if DRILL_FAIL_CREATE=1 bash "$SRC/scripts/backup_restore_drill.sh" > "$T/out" 2>&1; then
  fail 'database creation failure was accepted'
fi
[[ -s "$T/log/created" && ! -s "$T/log/dropped" ]] || fail 'failed creation attempted to drop a database'
assert_clean
echo 'ok  failed creation leaves existing resources alone'

reset_log
if DRILL_FAIL_RESTORE=1 bash "$SRC/scripts/backup_restore_drill.sh" > "$T/out" 2>&1; then
  fail 'restore failure was accepted'
fi
[[ -s "$T/log/created" ]] || fail 'restore failed before database creation'
cmp -s "$T/log/created" "$T/log/dropped" || fail 'failed restore did not drop its own database'
assert_clean
echo 'ok  failed restore cleans its own resources'

reset_log
if DRILL_FAIL_DROP=1 bash "$SRC/scripts/backup_restore_drill.sh" > "$T/out" 2>&1; then
  fail 'database cleanup failure was accepted'
fi
grep -q 'failed to drop temporary database' "$T/out" || fail 'cleanup failure was not reported'
! grep -q 'I41 restore drill passed' "$T/out" || fail 'cleanup failure was reported as success'
assert_clean
echo 'ok  cleanup failure is reported'

reset_log
bash "$SRC/scripts/backup_restore_drill.sh" > "$T/out1" 2>&1 & first=$!
bash "$SRC/scripts/backup_restore_drill.sh" > "$T/out2" 2>&1 & second=$!
wait "$first" || fail 'first simultaneous restore failed'
wait "$second" || fail 'second simultaneous restore failed'
[[ "$(sort -u "$T/log/created" | wc -l)" -eq 2 ]] || fail 'simultaneous restores shared a database name'
[[ "$(sort -u "$T/log/raw" | wc -l)" -eq 2 ]] || fail 'simultaneous restores shared a dump path'
sort "$T/log/created" > "$T/created.sorted"
sort "$T/log/dropped" > "$T/dropped.sorted"
cmp -s "$T/created.sorted" "$T/dropped.sorted" || fail 'simultaneous restores dropped the wrong databases'
assert_clean
echo 'ok  simultaneous restores use and clean separate resources'
