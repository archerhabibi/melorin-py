#!/usr/bin/env bash
# Append a structured entry to the server-side operations log (var/ops-log.md).
# The file is intentionally NOT tracked by git (var/ is ignored) so it never blocks `git pull`.
#
# Interactive:   scripts/ops_log.sh
# One-liner:     scripts/ops_log.sh -a "area" -b "before" -p "problem" -c "action" -r "after" [-w "who"] [-f "ref"]
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="${OPS_LOG:-var/ops-log.md}"
mkdir -p "$(dirname "$LOG")"
[ -f "$LOG" ] || printf '# Melorin server operations log\n\n' > "$LOG"

who="${SUDO_USER:-${USER:-unknown}}"; area=""; before=""; problem=""; action=""; after=""; ref=""
while getopts "w:a:b:p:c:r:f:" o; do
  case "$o" in
    w) who="$OPTARG";; a) area="$OPTARG";; b) before="$OPTARG";; p) problem="$OPTARG";;
    c) action="$OPTARG";; r) after="$OPTARG";; f) ref="$OPTARG";;
    *) exit 2;;
  esac
done
ask() { local v; read -r -p "$1: " v; printf '%s' "$v"; }
if [ -z "$area" ] && [ -t 0 ]; then
  area=$(ask "Area (api/worker/bot/web/db/infra/env)")
  before=$(ask "Before (state prior to change)")
  problem=$(ask "Problem / error")
  action=$(ask "Action taken")
  after=$(ask "After (verified result)")
  ref=$(ask "Ref (commit/command, optional)")
fi
ts="$(date -u '+%Y-%m-%d %H:%M UTC')"
{
  printf '### %s - %s - %s\n' "$ts" "$who" "${area:-general}"
  printf -- '- **Before:** %s\n- **Problem:** %s\n- **Action:** %s\n- **After:** %s\n' \
    "${before:--}" "${problem:--}" "${action:--}" "${after:--}"
  [ -n "$ref" ] && printf -- '- **Ref:** %s\n' "$ref"
  printf '\n'
} >> "$LOG"
echo "logged to $LOG"
