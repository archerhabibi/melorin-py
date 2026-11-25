# GIT-STATE-REPORT (Phase 0)

| Item | Value |
|---|---|
| Repository | https://github.com/archerhabibi/melorin-py (public) |
| Default branch | `main` |
| Base SHA | `ee384d60ba89fa25b13a694545fc26b62e7ae14a` — "Merge pull request #129 … audit/deep-technical-review-2026-11-19" (2026-11-22 21:21 +0330) |
| Tracked files | 1173 |
| Commits on main | 1115 |
| Remote branches | 107 (57 merged into main, 50 not merged — mostly Dependabot) |
| Open PRs | 31 (all Dependabot except #65 by owner — not reviewed in this program) |
| Open issues | 0 |
| Rulesets | none |

## Branch protection on `main` (read from GitHub API)
- Required status check: `quality` (strict / up-to-date branch required).
- Required PR reviews: enabled, **0 approving reviews required**; stale reviews not dismissed; code-owner review off.
- `enforce_admins: true`, force-push and deletion disabled, linear history not required, signatures not required, conversation resolution not required.
- Merge methods allowed: merge commit, squash, rebase. `delete_branch_on_merge: false`.
- Security: Dependabot security updates ON, secret scanning ON, push protection ON.

## Observations (not yet findings)
- Only `quality` is a required check; `web-e2e` and `postgres-lane` jobs run on every PR but are not required by branch protection (to be verified by AI-07: required checks vs. CI job list).
- 0 required approvals: acceptable for a one-owner project; the audit plan's "human approval for sensitive changes" is therefore a process rule, not a technical gate.
- Previously merged audit branches already cover earlier findings (`fix/payments-intent-retry`, `fix/refund-disabled-gateway-config`, `fix/zarinpal-refund-credentials`, `fix/worker-lock-fail-closed`, `fix/worker-metrics-scrape`, `refactor/audit-r12…r21`, `audit/t-remediation*` are all ancestors of `main`). `docs/audits/2026-11-19-deep-technical-audit.fa.md` AUD-001…AUD-003, AUD-007, AUD-008 are therefore presumed *already fixed*; teams must re-verify, not re-report.
