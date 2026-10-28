#!/usr/bin/env bash
# Require the CI job ("quality") and a pull request before anything lands on main (audit W1 / P0-2).
# Needs a token with repo admin rights; run once from your own machine:
#   GH_TOKEN=<admin token> scripts/enable_branch_protection.sh archerhabibi/melorin-py [main]
# Prints the resulting protection summary. Safe to re-run.
# NOTE: with required checks, direct pushes to main are rejected. The 'Changelog' workflow therefore never pushes to main:
# it keeps a pull request open from chore/changelog-auto (CI is started with workflow_dispatch; auto-merge is requested, so
# enable "Allow auto-merge" and "Allow GitHub Actions to create pull requests" in the repository settings).
# Deploys are CI-gated by deploy.yml (workflow_run), so this is defence in depth.
set -euo pipefail
REPO="${1:?usage: $0 owner/repo [branch]}"; BRANCH="${2:-main}"
command -v gh >/dev/null || { echo "gh CLI is required" >&2; exit 1; }
gh api -X PUT "repos/${REPO}/branches/${BRANCH}/protection" --input - <<JSON
{
  "required_status_checks": {"strict": true, "contexts": ["quality", "postgres-lane"]},
  "enforce_admins": false,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
gh api "repos/${REPO}/branches/${BRANCH}/protection" --jq '{checks: .required_status_checks.contexts, pr_required: (.required_pull_request_reviews != null), force_push: .allow_force_pushes.enabled}'
