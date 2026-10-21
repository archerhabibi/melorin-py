# S105 + S106 — Protect `main`, enable GitHub security features

Date: 2026-10-21 · Depends on: S101, S104 · Tooling: `scripts/s105_s106_repo_hardening.sh apply|verify|rollback`

## Design
### S105 — branch protection on `main` (classic rule)
| Setting | Value | Reason |
|---|---|---|
| Pull request required | yes, 0 approvals | solo owner cannot approve own PR; the gate is CI |
| Required check | `quality`, bound to the github-actions app (id 15368) | another app or token cannot fake the check |
| Up to date before merge | yes | CI result applies to what will land |
| Force push / deletion | blocked | |
| Enforce for admins | yes | otherwise the owner token bypasses everything |
| Linear history | off (optional in the plan) | the repo allows merge, squash and rebase |
| `postgres-lane` | not required | the plan names only `quality`; add it once it is stable |

### S106 — Settings → Code security
Secret scanning, push protection, Dependabot alerts and Dependabot security updates: all on.

## Result (executed 2026-10-21, `verify` = all PASS)
- S105: all six protection checks PASS.
- S106: `secret_scanning` and `secret_scanning_push_protection` were already enabled; Dependabot security updates and alerts were disabled and are now enabled.
- Behavioural test (public repo, admin token): a fast-forward push `S102 → main` was rejected ("Changes must be made through a pull request", required check `quality`); deleting `main` was rejected; `main` stayed at `50dd5cb`.

## Known consequence — Changelog workflow
`.github/workflows/changelog.yml` pushes `docs/CHANGE_LOG.md` straight to `main` with `GITHUB_TOKEN`. With enforcement for admins and no bypass, **that push is now rejected** and the Changelog job will fail after each merge (the workflow's own message anticipates this). Nothing else breaks; Deploy is separate.
Options (decision needed, not applied here):
1. Keep as is and generate the changelog inside the PR (recommended; no bypass hole): run `scripts/changelog_auto.py` in CI on the PR branch or in a pre-merge step.
2. Add the github-actions app as a bypass actor via a repository ruleset. Weaker: any workflow with a write token, including one from a pushed branch, could then write to `main`.

## Acceptance
Direct push to `main` rejected (tested); a PR with red `quality` cannot be merged (enforced by the required check; first real PR confirms). Security features show "Enabled".

## Rollback
`GH_TOKEN=<admin> scripts/s105_s106_repo_hardening.sh rollback` (removes protection and disables the S106 features), or Settings → Branches / Code security.
