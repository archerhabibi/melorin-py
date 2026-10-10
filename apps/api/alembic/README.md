Run `alembic revision --autogenerate -m "initial"`, review the migration, then `alembic upgrade head`.
Never use `create_all()` in production. Migration checks run in CI against an empty DB and the prior schema.
