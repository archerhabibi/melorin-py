# S104 — Safety tag + working branch

Date: 2026-10-21 · Depends on: S101 (revoke token) · Tooling: `scripts/s104_safety_tag.sh`

## Design
Before any cleanup, freeze a restorable reference to `main` and open the branch where all later phases land.
- Annotated tag `pre-cleanup-2026-10-22` on `origin/main` (name as in the execution plan; created 2026-10-21, one day before the planned start date).
- Branch `chore/execution` created from the same commit.
- The script is idempotent: it never moves an existing tag, and reuses an existing branch.
- Credentials come from the environment (e.g. `GIT_CONFIG_*` extraheader); nothing is written to `.git/config`.

## Result (executed)
| Item | Value |
|---|---|
| `origin/main` at snapshot | `50dd5cbf59a35fb0409436f65e278b12eabf9e2f` |
| Tag `pre-cleanup-2026-10-22` | annotated, peels to `50dd5cb…` (verified through the GitHub API and locally) |
| Branch `chore/execution` | `50dd5cb…` (identical to main) |
| Re-run | reports "already on origin", nothing moved |

## Acceptance
Tag is visible on GitHub (Tags list) and `git rev-parse 'pre-cleanup-2026-10-22^{commit}'` equals the main commit above.

## Restore / rollback
- Restore main content: `git checkout pre-cleanup-2026-10-22` (or branch from it).
- Remove the tag: `scripts/s104_safety_tag.sh --rollback` (= `git push --delete origin pre-cleanup-2026-10-22`).
- Note: the tag protects commits only. Server state and the database are covered by the S203/S204 backups.
