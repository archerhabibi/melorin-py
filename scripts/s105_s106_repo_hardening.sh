#!/usr/bin/env bash
# S105 + S106 - protect `main` and enable GitHub security features. Needs a token with repo admin.
# Usage: GH_TOKEN=... scripts/s105_s106_repo_hardening.sh apply|verify|rollback [owner/repo] [branch]
# The token is read from the environment only.
set -Eeuo pipefail
: "${GH_TOKEN:?set GH_TOKEN}"
ACTION="${1:-verify}"; REPO="${2:-archerhabibi/melorin-py}"; BRANCH="${3:-main}"
API="https://api.github.com/repos/$REPO"
CHECK="quality"            # CI job name required by S105
ACTIONS_APP_ID=15368       # github-actions app: only its check may satisfy the gate
g() { curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" "$@"; }
code() { curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" "$@"; }

apply() {
  # S105: PR required (0 approvals, solo owner), `quality` required and branch up to date,
  # no force-push, no deletion, rules also apply to admins.
  g -X PUT "$API/branches/$BRANCH/protection" -d @- <<JSON | python3 -c 'import sys,json;d=json.load(sys.stdin);assert "url" in d,d;print("S105 applied")'
{"required_status_checks":{"strict":true,"checks":[{"context":"$CHECK","app_id":$ACTIONS_APP_ID}]},
 "enforce_admins":true,
 "required_pull_request_reviews":{"required_approving_review_count":0,"dismiss_stale_reviews":false},
 "restrictions":null,"allow_force_pushes":false,"allow_deletions":false,
 "required_linear_history":false,"required_conversation_resolution":false}
JSON
  # S106: secret scanning + push protection, Dependabot alerts + security updates.
  g -X PATCH "$API" -d '{"security_and_analysis":{"secret_scanning":{"status":"enabled"},"secret_scanning_push_protection":{"status":"enabled"},"dependabot_security_updates":{"status":"enabled"}}}' >/dev/null
  [[ "$(code -X PUT "$API/vulnerability-alerts")" == 204 ]] && echo "S106 Dependabot alerts enabled"
  [[ "$(code -X PUT "$API/automated-security-fixes")" =~ ^20 ]] && echo "S106 Dependabot security updates enabled" || true
}

verify() {
  local rc=0
  g "$API/branches/$BRANCH/protection" | python3 -c '
import sys, json
d = json.load(sys.stdin); ok = True
def chk(n, c):
    global ok; print(("PASS " if c else "FAIL ") + n); ok = ok and c
if "message" in d: print("FAIL main is not protected:", d["message"]); sys.exit(1)
rsc = d.get("required_status_checks") or {}
chk("required check quality", any(c["context"] == "'$CHECK'" for c in rsc.get("checks", [])))
chk("branch must be up to date", rsc.get("strict") is True)
chk("pull request required", "required_pull_request_reviews" in d)
chk("admins included", d["enforce_admins"]["enabled"] is True)
chk("force push blocked", d["allow_force_pushes"]["enabled"] is False)
chk("deletion blocked", d["allow_deletions"]["enabled"] is False)
sys.exit(0 if ok else 1)' || rc=1
  g "$API" | python3 -c '
import sys, json
s = json.load(sys.stdin).get("security_and_analysis") or {}; ok = True
for k in ("secret_scanning", "secret_scanning_push_protection", "dependabot_security_updates"):
    v = (s.get(k) or {}).get("status"); print(("PASS " if v == "enabled" else "FAIL ") + k + ": " + str(v)); ok = ok and v == "enabled"
sys.exit(0 if ok else 1)' || rc=1
  [[ "$(code "$API/vulnerability-alerts")" == 204 ]] && echo "PASS dependabot alerts: enabled" || { echo "FAIL dependabot alerts"; rc=1; }
  return $rc
}

rollback() {
  g -X DELETE "$API/branches/$BRANCH/protection" -o /dev/null -w 'S105 protection removed (%{http_code})\n'
  g -X PATCH "$API" -d '{"security_and_analysis":{"secret_scanning_push_protection":{"status":"disabled"},"secret_scanning":{"status":"disabled"},"dependabot_security_updates":{"status":"disabled"}}}' >/dev/null
  code -X DELETE "$API/vulnerability-alerts" >/dev/null; echo "S106 features disabled"
}

case "$ACTION" in apply) apply; verify ;; verify) verify ;; rollback) rollback ;; *) sed -n 2,4p "$0"; exit 64 ;; esac
