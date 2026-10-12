# I17: first-install bootstrap

Run `python -m melorin.cli bootstrap` after migrations. The command is
idempotent: it creates or reuses the configured super-admin, main store,
owner membership, and default runtime settings.

Set `MELORIN_SEED_DEMO_DATA=true` only in development when a hidden test
product should also be created. Production bootstrap never enables demo data
unless explicitly configured.
