#!/usr/bin/env bash
# Check that each backup job prunes only its own top-level artifacts.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf -- "$T"' EXIT
mkdir -p "$T/bin" "$T/backups/nested" "$T/panel-source"
printf 'recipient' > "$T/recipients"
printf 'panel data' > "$T/panel-source/data"

cat > "$T/bin/psql" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
cat > "$T/bin/pg_dump" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
for arg in "$@"; do
  case "$arg" in --file=*) raw="${arg#--file=}" ;; esac
done
printf 'synthetic dump' > "$raw"
STUB
cat > "$T/bin/age" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
while (($#)); do
  case "$1" in
    --encrypt) shift ;;
    --recipients-file) shift 2 ;;
    --output) out="$2"; shift 2 ;;
    *) raw="$1"; shift ;;
  esac
done
cp -- "$raw" "$out"
STUB
chmod +x "$T/bin/"*
export PATH="$T/bin:$PATH"
export MELORIN_BACKUP_DIR="$T/backups" MELORIN_BACKUP_RETENTION_DAYS=30 MELORIN_BACKUP_RECIPIENT_FILE="$T/recipients"
export MELORIN_DATABASE_URL='postgresql://test:test@127.0.0.1/test' MELORIN_PANEL_BACKUP_PATHS="$T/panel-source"
unset MELORIN_PANEL_BACKUP_DATABASE_URL MELORIN_BACKUP_OFFSITE_URI || true

main_old="$T/backups/melorin-20000101T000000Z.dump.age"
panel_old="$T/backups/panel-20000101T000000Z.tar.age"
other="$T/backups/nested/notes.txt"
nested_main="$T/backups/nested/melorin-20000101T000000Z.dump.age"
nested_panel="$T/backups/nested/panel-20000101T000000Z.tar.age"
for f in "$main_old" "$main_old.sha256" "$panel_old" "$panel_old.sha256" "$other" "$nested_main" "$nested_panel"; do
  printf 'keep or expire' > "$f"
  touch -d '45 days ago' "$f"
done
fail() { echo "FAIL: $*" >&2; exit 1; }

bash "$SRC/scripts/backup_secure.sh" > "$T/main.log" 2>&1 || fail 'main backup failed'
main_new="$(tail -n1 "$T/main.log")"
[[ -f "$main_new" && -f "$main_new.sha256" ]] || fail 'main backup or checksum missing'
[[ ! -e "$main_old" && ! -e "$main_old.sha256" ]] || fail 'old main backup was not pruned'
[[ -f "$panel_old" && -f "$panel_old.sha256" && -f "$other" && -f "$nested_main" && -f "$nested_panel" ]] || fail 'main retention removed another file'
echo 'ok  main retention removes only its own top-level backups'

bash "$SRC/scripts/backup_panel.sh" > "$T/panel.log" 2>&1 || fail 'panel backup failed'
panel_new="$(tail -n1 "$T/panel.log")"
[[ -f "$panel_new" && -f "$panel_new.sha256" ]] || fail 'panel backup or checksum missing'
[[ ! -e "$panel_old" && ! -e "$panel_old.sha256" ]] || fail 'old panel backup was not pruned'
[[ -f "$main_new" && -f "$main_new.sha256" && -f "$other" && -f "$nested_main" && -f "$nested_panel" ]] || fail 'panel retention removed another file'
echo 'ok  panel retention removes only its own top-level backups'
