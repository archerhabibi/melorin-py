# Contributing to Melorin

These rules apply to everyone who changes this project: maintainers, contractors, and AI assistants
(Claude, Copilot, etc.) alike.

## 1. The change log is mandatory

Every change must be recorded - code in `docs/CHANGE_LOG.md`, server actions in `var/ops-log.md` - with **before, problem, action and after**.

You do not have to remember to do it: the `Changelog` workflow adds an entry for every commit pushed to `main`
that does not already contain one. Entries made this way say "not provided by the author" for facts they cannot
know. Do better - put the facts in the commit message as single-line trailers:

```
Fix wallet rounding on reseller refunds

Area: wallet
Before: refunds were rounded per line and could be 1 toman off
Problem: ledger total did not match the order total
Action: compute refunds in integer minor units
After: tests/test_wallet.py passes; ledger reconciles
```

`make setup-git` installs a commit template with these fields. Alternatively, write the entry yourself in
`docs/CHANGE_LOG.md` in the same commit; the bot then skips that commit.

**Anything done on the server -> `var/ops-log.md`.** `scripts/ops_watch.sh` (cron, every 5 minutes) records changed
commits, `.env` key changes (names only), hand-edited files and container restarts automatically, and the deploy
workflow records every deploy. It cannot know the reason, so run `scripts/ops_log.sh` and describe what was wrong,
what you did to fix it and the result.

Never put secrets (tokens, passwords, keys, `.env` values) in the change log, commit messages or issues.

## 2. Working rules

- Do not commit `.env`, certificates, age identities or real credentials.
- Do not edit tracked files directly on the server; change them in git and deploy. Server-side edits block
  `git pull --ff-only`.
- Run `make lint` and `make test` before pushing. Database changes need an Alembic migration.
- Respect the layering enforced by `lint-imports` (contracts in `apps/api/pyproject.toml`, run by `make lint` and CI):
  `domain` (pure) <- `kernel` (ORM models, `Base`) <- `core` (infrastructure) <- feature `modules` (an acyclic stack:
  admin > reports > reseller > orders/payments/identity > catalog/referral/tickets > vpn/wallet/webhooks/...) .
  `channels/*` are adapters and never import admin, reseller, reports, the worker or the entry points.
  New cross-module needs go through a lower layer or an outbox event, never a back-import.
- Validation with many independent checks (settings, coupon definitions) is written as an ordered rule table, not a long
  `if` chain; pin new rules with a test that asserts the code/message and the order.
- `github-actions[bot]` adds a commit with the change log after your push; run `git pull --rebase` before pushing again.

## 3. Pull requests

Use the PR template: it asks for the same before / problem / action / after information.
