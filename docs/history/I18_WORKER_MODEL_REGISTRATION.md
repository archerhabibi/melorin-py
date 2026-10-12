# I18: worker model registration

Both worker entrypoints share `melorin.worker.runner`, which now imports the
complete `melorin.models` registry before any worker session or mapper query is
created. This prevents SQLAlchemy from raising `NoReferencedTableError` for
relationships such as `orders.store_id -> stores.id` on a fresh worker boot.

The worker still requires the normal runtime dependencies and PostgreSQL/Redis
services for an end-to-end smoke run.
