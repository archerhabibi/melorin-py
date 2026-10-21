#!/usr/bin/env bash
# S102 - read-only review of what a leaked GitHub token could have touched.
# Usage: GH_TOKEN=<read-only token> scripts/s102_token_exposure_audit.sh [owner/repo] [outdir]
# The token is read from the environment only; it is never written to disk.
set -Eeuo pipefail
: "${GH_TOKEN:?set GH_TOKEN (use a fine-grained, read-only token)}"
REPO="${1:-archerhabibi/melorin-py}"
OUT="${2:-s102-evidence}"
API="https://api.github.com/repos/$REPO"
mkdir -p "$OUT"
g() { curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" "$@"; }

for ep in collaborators invitations keys hooks branches tags releases rulesets \
          actions/workflows actions/secrets actions/variables actions/permissions \
          environments dependabot/secrets forks; do
  g "$API/$ep?per_page=100" > "$OUT/$(echo "$ep" | tr / _).json"
done
g "$API/actions/runs?per_page=100" > "$OUT/actions_runs.json"
g "$API/events?per_page=100"       > "$OUT/events.json"
g "$API/branches/main/protection"  > "$OUT/main_protection.json" || true

python3 - "$OUT" <<'PY'
import json, sys, collections, pathlib
o = pathlib.Path(sys.argv[1]); L = lambda n: json.loads((o / n).read_text())
cnt = lambda n, k=None: (lambda d: len(d[k]) if k else len(d))(L(n))
findings = []
def flag(c, m):
    if c: findings.append(m)
flag(cnt("collaborators.json") != 1, "collaborators != 1")
flag(cnt("invitations.json") > 0, "pending invitations")
flag(cnt("keys.json") > 0, "deploy keys present")
flag(cnt("hooks.json") > 0, "webhooks present")
flag(L("actions_secrets.json").get("total_count", 0) > 0, "Actions secrets exist (rotate: S103)")
flag(cnt("forks.json") > 0, "forks exist")
runs = L("actions_runs.json")["workflow_runs"]
actors = {r["actor"]["login"] for r in runs}
flag(bool(actors - {"archerhabibi", "dependabot[bot]", "github-actions[bot]"}), f"unexpected run actors: {actors}")
print("collaborators:", cnt("collaborators.json"), "| deploy keys:", cnt("keys.json"),
      "| webhooks:", cnt("hooks.json"), "| actions secrets:", L("actions_secrets.json").get("total_count"))
print("run actors:", sorted(actors))
print("FINDINGS:", findings or "none")
PY
