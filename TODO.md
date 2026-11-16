# TODO: audit + account-linking checklist

Source: docs/AUDIT-2026-11-15.md and docs/25-Person-Account-Linking-Design.md (branch feat/person-account-linking).
Status verified against the current code, not the audit text.

## Audit items
- [x] 1. gen_docs --check guard (fixed before this branch)
- [x] 2. SettingsView double import (fixed)
- [x] 3. System/security menu grouping (fixed)
- [x] 4. one-shot `migrate` service in docker-compose.yml; api/worker/backup depend on it (already present)
- [x] 5. packages/web-kit/package-lock.json is tracked (already present)
- [ ] 6. authFetch: 2 real call sites left (AdminSession CSV export, ReportsParts CSV download). Blob/CSV downloads cannot use the JSON typedClient; kept on purpose.
- [x] 7. mypy covers all of `melorin` (362 files); 3 new errors on this branch fixed
- [x] 8. dead code: CursorResult import is used for typing; `initiator` is a SQLAlchemy event parameter (`_initiator`)
- [x] 9. bandit B104 annotated with `# nosec B104` and reason; bandit -ll is clean
- [x] 10. ops_watch.sh unused APP removed; melorin.sh SC2097/SC2098 not reproducible: shellcheck not installable here
- [x] 11. large panel files: all now under 540 lines
- [x] 12. no skipped Playwright specs remain in e2e/tests
- [x] 13. decided in r15/r17: stays infrastructure-only (docs/DECISIONS.md)
- [x] 14. decided in r15/r17: stays in the system area (docs/DECISIONS.md)

## Account-linking (doc 25 "remaining")
- [x] A. Site UI: dashboard tab "linked accounts" + landing section (store-web, 4 tests)
- [x] B. Telegram bot: always-visible main-menu button + screen (3 tests). Needs a real bot token to try live.
- [x] C. HTTP and financial tests for consolidation (5 tests) and reauth/unlink (4 tests)
- [x] D. Reauth for passwordless users: e-mail one-time code. Telegram/Google-only accounts without e-mail keep session proof + last-method guard (product decision pending, see below)
- [x] E. decided: session proof + last-method guard for accounts with no password and no e-mail (docs/DECISIONS.md); a stronger proof is future work
- [x] F. README.fa.md has no matching identity row, nothing to mirror

## Cannot be verified here
Docker/Compose (no docker on the test server), real Telegram bots, payment gateways, PasarGuard, TLS/Caddy.
