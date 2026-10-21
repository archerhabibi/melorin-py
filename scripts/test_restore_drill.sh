#!/usr/bin/env bash
# Offline test for scripts/restore_drill_latest.sh: backup_restore_drill.sh is replaced by a stub that only verifies the checksum
# (the real one needs age + PostgreSQL). Proves: newest backup is chosen, a checksum recorded under the production path is accepted,
# a corrupted archive is rejected, a stale backup violates the RPO, and the result is logged.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/scripts" "$T/backups" "$T/var"
cp "$SRC/scripts/restore_drill_latest.sh" "$T/scripts/"
cat > "$T/scripts/backup_restore_drill.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
sha256sum --check "$BACKUP_CHECKSUM_FILE" >/dev/null
echo "I41 restore drill passed (stub): archive=$(basename "$BACKUP_ARCHIVE")"
STUB
chmod +x "$T/scripts/"*.sh
fail() { echo "FAIL: $*"; exit 1; }
stamp() { date -u -d "$1" +%Y%m%dT%H%M%SZ; }
mk() { # mk <iso-time> -> creates a fake backup whose .sha256 uses a foreign absolute path, like backup_secure.sh on the server
  local f; f="melorin-$(stamp "$1").dump.age"
  printf 'payload-%s' "$1" > "$T/backups/$f"
  printf '%s  /app/var/backups/%s\n' "$(sha256sum "$T/backups/$f" | cut -d' ' -f1)" "$f" > "$T/backups/$f.sha256"
  echo "$f"
}
drill() { ( cd "$T"; env BACKUP_SOURCE="$T/backups" BACKUP_IDENTITY_FILE=/dev/null MELORIN_DATABASE_URL=postgresql://u:p@h/db \
  RESTORE_DRILL_LOG="$T/var/drill.log" "$@" bash scripts/restore_drill_latest.sh 2>&1 ); }

old="$(mk '3 days ago')"; new="$(mk '2 hours ago')"
out="$(drill MELORIN_RPO_HOURS=24)" || fail "good backup rejected: $out"
grep -q "$new" <<<"$out" || fail "newest backup not chosen: $out"
grep -q "RESTORE DRILL OK" "$T/var/drill.log" || fail "result not logged"
echo "ok  1 newest backup restored, foreign checksum path accepted"

printf 'tampered' >> "$T/backups/$new"
set +e; out="$(drill MELORIN_RPO_HOURS=24)"; rc=$?; set -e
[ "$rc" = 1 ] && grep -q "RESTORE DRILL FAILED" <<<"$out" || fail "corrupted archive not rejected (rc=$rc): $out"
echo "ok  2 corrupted archive rejected"

rm -f "$T/backups/$new" "$T/backups/$new.sha256"
set +e; out="$(drill MELORIN_RPO_HOURS=24)"; rc=$?; set -e
[ "$rc" = 1 ] && grep -q "RPO" <<<"$out" || fail "stale backup ($old) not flagged (rc=$rc): $out"
echo "ok  3 stale backup violates RPO"
echo "restore drill tests passed"
