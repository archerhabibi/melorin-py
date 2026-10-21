# S103 — Rotate secrets reachable by the leaked token

Date: 2026-10-21 · Depends on: S101 (revoke token), S102 (exposure review) · Tooling: `scripts/s103_rotate_secrets.sh`

## Design
Scope = secrets a holder of the leaked admin token could have read or caused to be read.
S102 found **0 Actions secrets, 0 variables, 0 environments, 0 deploy keys**, so no Actions secret was reachable.
Exposure therefore reduces to: (A) the SSH path used by `deploy.yml` (secrets are *not yet configured*, deploy runs fail), and
(B) anything that was ever committed (history scan: only fake test tokens). Server-side `.env` values were never in GitHub.

Decision rules
1. **Do not create new secrets while the old token is alive.** An admin token can edit workflows and exfiltrate any new secret. Finish S101 first.
2. Rotation is **create new → install → verify → remove old**. Old access stays at most 1 hour (S103 rollback rule).
3. Private keys never touch the repo or chat; only the public key is displayed.

## Procedure
### A. Deploy SSH key (required before enabling deploy, S202/S203)
1. Operator machine: `scripts/s103_rotate_secrets.sh gen-deploy-key ~/melorin-keys`.
2. Server: append the printed public key to `~/.ssh/authorized_keys` of the deploy user. Restrict it: prefix `restrict,command="…"` if a forced command is used later (S203).
3. `scripts/s103_rotate_secrets.sh verify-key ~/melorin-keys/id_deploy_<date> user@host [port]` → `OK`.
4. With the **new fine-grained token** (S101) or the GitHub UI, set repo secrets `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT`. Run the Deploy workflow manually (`workflow_dispatch`).
5. Server: run `scripts/s103_rotate_secrets.sh audit-authorized-keys`; delete every key you do not recognise, including the previous deploy key. Then `verify-rejected <old key> user@host` → `OK`.
6. Shred the local private key file after the secret is stored (`shred -u`).

### B. Application secrets (rotate if the server or its `.env` was ever exposed, or as precaution)
Generate: `scripts/s103_rotate_secrets.sh gen-app-secrets ./new-secrets.env` (mode 600, refuses to overwrite).
| Secret | Effect of rotating | How |
|---|---|---|
| `MELORIN_JWT_SECRET` | all sessions invalid, users log in again | edit `.env`, `docker compose up -d api worker` |
| `MELORIN_BOT_SERVICE_SECRET`, `MELORIN_MAIN_BOT_SECRET`, `MELORIN_RESELLER_BOT_SECRET` | bots and API must carry the same value | change in `.env`, restart `api worker telegram_*` together |
| `MELORIN_METRICS_TOKEN`, `MELORIN_HEALTH_TOKEN` | update Prometheus/uptime monitors | `.env` + monitor config |
| `MELORIN_ENCRYPTION_KEY` | stored bot tokens must be re-encrypted | `python -m melorin.cli rotate-encryption-key <NEW_FERNET_KEY>` (see docs/history/I36), **take a backup first** |
| Telegram bot tokens | only if leaked: revoke in @BotFather, store new value | `.env`, restart bots |
| `POSTGRES_PASSWORD` | DB URL must change too | `ALTER USER`, update `MELORIN_DATABASE_URL`, restart |
| S3/rclone keys (`MELORIN_BACKUP_OFFSITE_URI` remote) | only if stored in GitHub (none found) | rotate at provider, update rclone config on server |
Delete `new-secrets.env` after applying.

## Acceptance
- Old SSH key rejected (`verify-rejected`), new key accepted (`verify-key`), manual Deploy run authenticates.
- `authorized_keys` audit lists only recognised keys.
- `GET /health/ready` OK after secret changes; bots reply; admin can log in.

## Status of this run (2026-10-21)
- Repo-side evidence: nothing reachable in Actions (see S102). Design and tooling committed.
- **Not executed by Claude:** steps A.2–A.6 and B need server/provider access and must not use the leaked token. Pending: S101 revocation (token still returned 200 at the time of writing).

## Rollback
Keep the old key in `authorized_keys` for at most 1 hour until the new one is verified; if the new key fails, remove it and retry from step A.1.
