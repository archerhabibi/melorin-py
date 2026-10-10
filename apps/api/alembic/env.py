import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from melorin.core.config import get_settings
from melorin.core.db import Base
from melorin import models  # noqa: F401: register all tables

a = context.config
if a.config_file_name: fileConfig(a.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=get_settings().database_url.replace("+asyncpg", ""), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction(): context.run_migrations()

async def run_async():
    connectable = async_engine_from_config(a.get_section(a.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool, url=get_settings().database_url)
    async with connectable.connect() as c:
        await c.run_sync(lambda conn: context.configure(connection=conn, target_metadata=target_metadata, compare_type=True))
        await c.run_sync(lambda conn: context.run_migrations())
        await c.commit()
    await connectable.dispose()

def run_migrations_online(): asyncio.run(run_async())

run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
