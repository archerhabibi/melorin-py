# S102 — Token exposure review

Date: 2026-10-21 · Repo: archerhabibi/melorin-py · Base: `main` @ 50dd5cb · Branch: `S102`
Scope: what the leaked token (admin on this repo) could have touched (task S102, threat T3).
Method: GitHub REST API (read-only calls) + full-history git review. Repeatable via
`scripts/s102_token_exposure_audit.sh`. The token value is not stored anywhere in the repo.

## Result
**No unexpected change found.** No evidence of persistence, exfiltration or tampering.

## Evidence
| Area | Observation | Verdict |
|---|---|---|
| Collaborators / invitations / forks | 1 collaborator (owner), 0 invitations, 0 forks | OK |
| Deploy keys / webhooks / autolinks | 0 / 0 / 0 | OK |
| Actions secrets, variables, environments | 0 secrets, 0 variables, 0 environments (so nothing for a workflow to exfiltrate; the 15 Deploy runs all failed) | OK, see note 1 |
| Workflows | 4 (Changelog, CI, Deploy, Dependabot). `deploy.yml` last changed 2026-10-12 (commit 3b2262a, before the recorded activity window) | OK |
| Workflow changes on branches | `ci/diagnose-e2e`, `ci/pin-ubuntu-24.04`, `fix/ci-guards`: only log redirection, runner pin, DB reset before `alembic check`. No network calls, no secret use | OK |
| Exfil patterns in all workflow versions | No curl/wget to external hosts, no base64/eval of secrets; only `localhost` health probes | OK |
| Workflow runs (480 total, last 100 inspected) | Actors only `archerhabibi`, `dependabot[bot]`; events push / pull_request; no `workflow_dispatch` by others | OK |
| Branches / tags / releases | 22 branches (18 Dependabot, rest feature/CI branches by owner), 0 tags, 0 releases | OK |
| PRs / issues | Only owner and Dependabot | OK |
| Commit authors (all refs) | Owner, Claude sessions, github-actions, Dependabot, `Melorin M6`, `melorin`, `x <a@b.c>`, `renewal-design`, `Parsian`, `hassanhabibi`: all consistent with the project history (patch-based work, installer commits) | OK, see note 2 |
| Secrets committed in history | Only the fake bot token `123456789:AAH-secret_token_value_...` in tests (marked allowlist) | OK |
| Branch protection / rulesets | `main` unprotected, no rulesets | Gap, fixed by S105 |
| Events (last 100) | Only owner/bots; 19 delete events on 2026-10-21 17:07Z are merged-branch cleanups | OK, see note 3 |

## Notes and limits
1. Secrets: 0 Actions secrets means `DEPLOY_SSH_KEY` is not configured on this repo. S103 should still confirm that the server's `authorized_keys` contain no unexpected keys, and that any key which was ever stored elsewhere is rotated.
2. Commit author names are self-declared and unsigned in most cases (most commits show `verified: false`), so authorship alone proves nothing. Content review found nothing malicious.
3. The user-level Audit log (Settings, Security log) is not exposed by the API for personal accounts; check it manually for token use from unknown IPs/dates (Settings → Security log → filter `oauth_access`/`repo.*`). Events here cannot distinguish a token holder from the owner, because the token acts as the owner.
4. The repository is **public**; anything pushed was world-readable.

## Follow-ups
- S101 (revoke token) must be completed first; this review used the token read-only until then.
- S103 server-side `authorized_keys` check; S105 branch protection; S106 secret scanning + push protection.
