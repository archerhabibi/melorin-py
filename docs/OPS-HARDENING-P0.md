# Ops hardening (audit phases P0 / P9)

Status: procedure. Source: `T-AUDIT-2026-11-09` (T17, T20, T21, T25, T28, T32, T33, T47, T48, T53).
Code-side parts of P0 (log redaction T20/T40, 429 handling T22) already live in `core/logging.py` and the bots; this page covers what only an operator can do on the server.

## 1. Rotate credentials (do first, in this order)

| Credential | Why | How |
|---|---|---|
| GitHub token pasted into a chat (T21) | A token that was shared in text must be treated as leaked | GitHub -> Settings -> Developer settings -> revoke it. Create a **fine-grained** token limited to this repository (Contents + Pull requests: read/write), 30-day expiry |
| Main bot and every reseller bot token (T20) | Old tracebacks in `docker logs` contained the full token URL | BotFather `/revoke`, put the new token in `.env` / the store row, restart only that bot |
| Anything else that appeared in logs or `.env.bak.*` (T33) | Backup copies of `.env` keep old secrets alive | Rotate, then delete the backup file |

After rotating, confirm the logs are clean:

```bash
docker logs --since 24h telegram_main 2>&1 | grep -Eoi 'bot[0-9]{6,}:[A-Za-z0-9_-]{20,}' | head   # must print nothing
```

## 2. Host hardening script

`scripts/harden_host.sh` is a dry run by default.

```bash
sudo scripts/harden_host.sh                      # shows every change
sudo SSH_PORT=22 NODE_IPS="203.0.113.10" scripts/harden_host.sh --apply
```

It: enables `ufw` (SSH is allowed first; 80/443 open; panel node ports only for `NODE_IPS`), adds a 2 GiB swap file (T25), encrypts or `chmod 600`s plaintext `.sql` dumps (T32) and **lists** (never deletes) untracked files in `/opt/melorin` and extra project copies (T33, T17).
Docker edits iptables itself, so also make sure containers publish `127.0.0.1:PORT` only.

## 3. Before every cleanup phase

```bash
scripts/phase_snapshot.sh P2 --backup   # annotated tag + encrypted backup
git push origin pre-P2-<timestamp>
```

Test on `/opt/melorin-stage`, never on production first. Roll back by checking out the tag.

## 4. Repository access

* Give each collaborator **write** access; never share your own token.
* Branch protection on `main`: one approving review, required CI checks (`ruff`, `lint-imports`, `pytest`, `gen_docs --check`), no force-push.

## 5. Verify (T48, T53)

* Admin panel -> backup settings: confirm `backup_s3` (off-server copy) is enabled.
* Run `scripts/restore_drill_latest.sh` on staging and record the date in `docs/STATUS.md`.
