# Contributing to Melorin

These rules apply to everyone who changes this project: maintainers, contractors, and AI assistants
(Claude, Copilot, etc.) alike.

## 1. The change log is mandatory

Every change must end up in `docs/CHANGE_LOG.md` with **before, problem, action and after**.

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

Work done directly on the server (it does not appear in git) must be recorded the same way: add an entry to
`docs/CHANGE_LOG.md` and commit it.

Never put secrets (tokens, passwords, keys, `.env` values) in the change log, commit messages or issues.

## 2. Working rules

- Do not commit `.env`, certificates, age identities or real credentials.
- Do not edit tracked files directly on the server; change them in git and deploy. Server-side edits block
  `git pull --ff-only`.
- Run `make lint` and `make test` before pushing. Database changes need an Alembic migration.
- `github-actions[bot]` adds a commit with the change log after your push; run `git pull --rebase` before pushing again.

## 3. Pull requests

Use the PR template: it asks for the same before / problem / action / after information.
