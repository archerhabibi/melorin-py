# Melorin Change Log

Every change to the project (by anyone: owner, Claude, contractors) is recorded here,
newest first. Git history keeps the exact diff; this file keeps the *why*.

## It fills itself - nobody has to remember

`.github/workflows/changelog.yml` runs `scripts/changelog_auto.py` on **every push to `main`** and commits an entry
for each commit that does not already have one, so the log is complete even for people who do not know it exists.

Auto entries are honest: fields the author did not supply say "_not provided by the author_".
To make an entry complete without editing this file, put single-line trailers in the commit message
(`make setup-git` enables a template): `Area:`, `Before:`, `Problem:`, `Action:`, `After:`.
A commit that edits this file itself is considered already documented and is skipped.
Commits containing `[skip changelog]` and the bot's own commits are skipped.
If `main` is protected, allow `github-actions[bot]` to bypass so the bot can push the log.
Changes made directly on the server are not visible to git: record them yourself (commit a note here).

## Entry template

```
### YYYY-MM-DD HH:MM UTC - <who> - <area>
- **Before:** state/behaviour before the change
- **Problem:** the bug, error or missing piece (with error text / evidence)
- **Action:** what was changed to fix it (files, commands)
- **After:** verified result (tests run, health check, screenshot)
- **Ref:** commit hash / PR
```

Never write secrets (tokens, passwords, keys, `.env` values) in this file.

---

<!-- AUTO-ENTRIES-BELOW (newest first) -->

### 2026-10-11 - Claude (with owner) - reset to 27b7ee5 and re-applied the agreed changes
- **Before:** `main` carried extra commits (custom ports, TLS-from-files, SMTP/backup installer, server-side logging).
- **Problem:** owner asked to return to commit 27b7ee5 and redo only: main-bot token at install, automatic change
  log, README with install steps, and the optional SMTP/S3 patch refreshed for 27b7ee5.
- **Action:** history reset to 27b7ee5; then added (1) `docs`/Admin-panel optional SMTP and S3 backup patch
  (`optional-smtp-s3`, installer hunk removed because 27b7ee5 had no installer), (2) `scripts/install_server.sh`
  asking for the main bot token, local age-encrypted backups, reseller bot behind compose profile `reseller`,
  (3) automatic change log (`changelog.yml`, `changelog_auto.py`, `.gitmessage`, `make setup-git`),
  (4) README install guide, `README.fa.md`, `CONTRIBUTING.md`, PR template.
- **After:** patch applies cleanly on 27b7ee5; test suite: 122 passed / 6 failed - the same 6 fail on plain
  27b7ee5 (not caused by the patch); the 7 new tests pass. Installer dry-run (stub docker): token prompt, invalid
  token handling and idempotent re-run OK. Real-server install and the GitHub workflows not yet run.
- **Ref:** this commit
