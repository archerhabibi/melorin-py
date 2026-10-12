# I22: CI quality gate

CI now invokes the existing `scripts/run_quality_gate.sh` entrypoint, and the
quality-gate path test resolves the repository root correctly. Web lockfile
validation runs after CI installs and builds both Web apps, while the general
gate no longer runs it before the lockfiles can exist.

The webhook private-IP guard was also corrected so its deliberate
`WebhookUrlError` is not swallowed by the hostname parsing exception handler.
