#!/usr/bin/env bash
# Automatic server-side change recorder. Runs every 5 minutes from cron (see install_ops_watch.sh)
# and appends an entry to var/ops-log.md whenever something changed that nobody logged:
#   * deployed git commit changed          * .env keys added/removed/changed (NAMES only, never values)
#   * tracked files edited by hand         * container recreated / restarted / became unhealthy / stopped
# It cannot know WHY something changed: entries say so, and people add the reason with scripts/ops_log.sh.
set -uo pipefail
cd "$(dirname "$0")/.."
APP="$(pwd)"
mkdir -p var
LOG="var/ops-log.md"; ST="var/.ops-watch"; mkdir -p "$ST"; chmod 700 "$ST" 2>/dev/null || true
exec 9>"$ST/lock"; flock -n 9 || exit 0

log() { # log area before problem action after [ref]
  scripts/ops_log.sh -w "auto-detected (logged-in: $(who 2>/dev/null | awk '{print $1}' | sort -u | paste -sd, - | sed 's/^$/nobody/'))" \
    -a "$1" -b "$2" -p "$3" -c "$4" -r "$5" ${6:+-f "$6"}
}
flat() { tr '\n' ';' | sed 's/;$//; s/;/; /g'; }
first_run=0; [ -f "$ST/head" ] || first_run=1

# --- 1. git HEAD / local edits -------------------------------------------------
if command -v git >/dev/null 2>&1 && [ -d .git ]; then
  head=$(git rev-parse --short HEAD 2>/dev/null)
  prev=$(cat "$ST/head" 2>/dev/null || true)
  if [ -n "$prev" ] && [ "$prev" != "$head" ]; then
    # skip if the deploy workflow already logged this ref
    if ! grep -q "$head" "$LOG" 2>/dev/null; then
      n=$(git diff --name-only "$prev" "$head" 2>/dev/null | wc -l)
      subj=$(git log --format='%h %an: %s' "$prev..$head" 2>/dev/null | head -5 | flat)
      log deploy "commit $prev" "reason not provided" "code moved to $head ($n files): ${subj:-history rewritten}" "now $head" "$head"
    fi
  fi
  echo "$head" > "$ST/head"
  dirty=$(git status --porcelain --untracked-files=no 2>/dev/null | awk '{print $2}' | sort)
  dh=$(printf '%s' "$dirty" | sha256sum | cut -d' ' -f1); pdh=$(cat "$ST/dirty" 2>/dev/null || true)
  if [ -n "$pdh" ] && [ "$dh" != "$pdh" ]; then
    if [ -n "$dirty" ]; then
      log config "clean checkout" "tracked files edited directly on the server (blocks 'git pull --ff-only')" "files: $(echo "$dirty" | flat)" "drift from git" "$head"
    else
      log config "tracked files modified" "-" "local modifications gone (reverted or committed)" "clean checkout" "$head"
    fi
  fi
  echo "$dh" > "$ST/dirty"
fi

# --- 2. .env: key names whose value changed (hash per key, values never stored in clear) ---
if [ -f .env ]; then
  grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env | while IFS='=' read -r k v; do
    printf '%s %s\n' "$k" "$(printf '%s' "$v" | sha256sum | cut -c1-16)"
  done | sort > "$ST/env.new"
  if [ -f "$ST/env" ]; then
    added=$(comm -13 <(cut -d' ' -f1 "$ST/env") <(cut -d' ' -f1 "$ST/env.new") | flat)
    removed=$(comm -23 <(cut -d' ' -f1 "$ST/env") <(cut -d' ' -f1 "$ST/env.new") | flat)
    changed=$(join "$ST/env" "$ST/env.new" | awk '$2!=$3{print $1}' | flat)
    if [ -n "$added$removed$changed" ]; then
      log env "previous .env" "reason not provided" ".env edited - added: ${added:--}; removed: ${removed:--}; changed values of: ${changed:--} (values not recorded)" "restart needed for changes to apply" ""
    fi
  fi
  mv "$ST/env.new" "$ST/env"; chmod 600 "$ST/env"
fi

# --- 3. containers ----------------------------------------------------------------
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker ps -a --filter label=com.docker.compose.project=melorin -q 2>/dev/null | while read -r id; do
    docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}} {{.Id}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.RestartCount}} {{.State.OOMKilled}}' "$id" 2>/dev/null
  done | sort > "$ST/ctr.new"
  if [ -f "$ST/ctr" ]; then
    msgs=""
    while read -r svc id state health rc oom; do
      read -r _ pid pstate phealth prc _ < <(grep "^$svc " "$ST/ctr" || echo "$svc - - - 0 -")
      [ "$pid" = "-" ] && { msgs+="$svc: new container; "; continue; }
      [ "$pid" != "$id" ] && msgs+="$svc: container recreated; "
      [ "$state" != "$pstate" ] && msgs+="$svc: $pstate -> $state; "
      [ "$health" = "unhealthy" ] && [ "$phealth" != "unhealthy" ] && msgs+="$svc: became UNHEALTHY; "
      [ "${rc:-0}" -gt "${prc:-0}" ] && msgs+="$svc: restarted (count $prc -> $rc); "
      [ "$oom" = "true" ] && msgs+="$svc: OOM-killed; "
    done < "$ST/ctr.new"
    [ -n "$msgs" ] && log containers "previous container state" "reason not provided" "$msgs" "see 'docker compose ps' / logs"
  fi
  mv "$ST/ctr.new" "$ST/ctr"
fi

[ "$first_run" = 1 ] && log ops-watch "-" "-" "automatic change recording started (baseline captured)" "watching git HEAD, .env keys, tracked-file drift, containers"
exit 0
