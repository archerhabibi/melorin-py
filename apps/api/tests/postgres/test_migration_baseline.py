"""The single Alembic baseline builds the exact model schema on an EMPTY PostgreSQL database (docs/19-DATABASE-MIGRATIONS.md).

Runs only when ``TEST_PG_ADMIN_URL`` (e.g. ``postgresql+asyncpg://user:pw@localhost/postgres``) is set; it creates and drops a scratch database.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

API = Path(__file__).resolve().parents[2]
ADMIN_URL = os.environ.get("TEST_PG_ADMIN_URL")

pytestmark = [pytest.mark.integration, pytest.mark.skipif(not ADMIN_URL, reason="TEST_PG_ADMIN_URL not set")]


def test_single_baseline_revision_exists():
    versions = sorted(p.name for p in (API / "alembic" / "versions").glob("*.py"))
    assert versions == ["0001_initial_baseline.py"]


def _alembic(url: str, *args: str) -> None:
    env = {**os.environ, "MELORIN_DATABASE_URL": url, "PYTHONPATH": str(API)}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API, env=env, check=True, capture_output=True)


async def _diff(url: str):
    from melorin import models  # noqa: F401
    from melorin.core.db import Base

    engine = create_async_engine(url)
    async with engine.connect() as conn:
        diffs = await conn.run_sync(lambda c: compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata))
        extras = {
            "seq": {r[0] for r in await conn.execute(text("select sequencename from pg_sequences"))},
            "trg": {r[0] for r in await conn.execute(text("select tgname from pg_trigger where not tgisinternal"))},
            "settings": {r[0] for r in await conn.execute(text("select key from system_settings"))},
        }
    await engine.dispose()
    return diffs, extras


async def _admin(sql: str) -> None:
    engine = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(sql))
    await engine.dispose()


async def _ledger_attacks(url: str) -> list[str]:
    """Seed one reversed ledger transaction, then try to rewrite history: the database error text of every attempt."""
    tx, rev, entry = (f"00000000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
    insert_tx = "INSERT INTO ledger_transactions (id, created_at, kind, idempotency_key, currency, reverses_id) VALUES ('{}', now(), 'k', '{}', 'IRT', {})"
    seed = [
        insert_tx.format(tx, "k1", "NULL"),
        f"INSERT INTO ledger_entries (id, created_at, transaction_id, account, amount) VALUES ('{entry}', now(), '{tx}', 'x', 5)",
        insert_tx.format(rev, "k2", f"'{tx}'"),
    ]
    attacks = [
        "UPDATE ledger_entries SET amount = 6",
        "DELETE FROM ledger_entries",
        "UPDATE ledger_transactions SET memo = 'x'",
        insert_tx.format("00000000-0000-0000-0000-000000000004", "k3", f"'{tx}'"),  # a second reversal of the same transaction
    ]
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        for sql in seed:
            await conn.execute(text(sql))
    errors = []
    for sql in attacks:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
            errors.append(f"NO ERROR: {sql}")
        except DBAPIError as exc:
            errors.append(str(exc.orig))
    await engine.dispose()
    return errors


def test_ledger_history_cannot_be_rewritten_and_a_transaction_is_reversed_once():
    name = f"melorin_bl_{uuid.uuid4().hex[:8]}"
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    asyncio.run(_admin(f"CREATE DATABASE {name}"))
    try:
        _alembic(url, "upgrade", "head")
        errors = asyncio.run(_ledger_attacks(url))
        assert all("append-only" in e for e in errors[:3]), errors
        assert "uq_ledger_transactions_reverses_id" in errors[3], errors
    finally:
        asyncio.run(_admin(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


def test_baseline_upgrade_from_empty_matches_models_and_is_repeatable():
    name = f"melorin_bl_{uuid.uuid4().hex[:8]}"
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    asyncio.run(_admin(f"CREATE DATABASE {name}"))
    try:
        _alembic(url, "upgrade", "head")
        diffs, extras = asyncio.run(_diff(url))
        assert diffs == []
        assert {"order_number_seq", "ticket_number_seq"} <= extras["seq"]
        assert {"account_link_audits_no_change", "ledger_entries_no_change", "ledger_transactions_no_change"} <= extras["trg"]
        assert {"provisioning.max_attempts", "provisioning.backoff_seconds"} <= extras["settings"]
        _alembic(url, "upgrade", "head")  # idempotent re-run
        _alembic(url, "downgrade", "base")
        _alembic(url, "upgrade", "head")
    finally:
        asyncio.run(_admin(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
