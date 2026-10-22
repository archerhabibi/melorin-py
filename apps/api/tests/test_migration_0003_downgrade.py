"""Migration 0003: downgrade must work on a fresh install, where the baseline created the three-column
idempotency constraint under a generated name, as well as on an already-swapped legacy schema."""

import importlib.util
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("m0003", ROOT / "alembic/versions/0003_f001_f010_hardening.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Recorder:
    def __init__(self):
        self.calls = []

    def get_bind(self):
        return object()

    def drop_constraint(self, name, table, type_=None):
        self.calls.append(("drop", name, table))

    def create_unique_constraint(self, name, table, cols):
        self.calls.append(("create", name, table, list(cols)))


def _run_downgrade(monkeypatch, layout):
    """layout: {table: [(constraint_name, [columns])]}"""
    m = _load()
    rec = _Recorder()
    inspector = SimpleNamespace(get_unique_constraints=lambda t: [{"name": n, "column_names": c} for n, c in layout[t]])
    monkeypatch.setattr(m, "op", rec)
    monkeypatch.setattr(m.sa, "inspect", lambda _bind: inspector)
    m.downgrade()
    return rec.calls


def test_downgrade_on_fresh_install_drops_the_generated_name_and_restores_the_legacy_constraint(monkeypatch):
    calls = _run_downgrade(
        monkeypatch,
        {
            "payments": [("uq_payments_user_id_store_id_idempotency_key", ["user_id", "store_id", "idempotency_key"])],
            "orders": [("uq_orders_user_id_store_id_idempotency_key", ["user_id", "store_id", "idempotency_key"])],
        },
    )
    assert calls == [
        ("drop", "uq_payments_user_id_store_id_idempotency_key", "payments"),
        ("create", "uq_payments_user_id_idempotency_key", "payments", ["user_id", "idempotency_key"]),
        ("drop", "uq_orders_user_id_store_id_idempotency_key", "orders"),
        ("create", "uq_orders_user_id_idempotency_key", "orders", ["user_id", "idempotency_key"]),
    ]


def test_downgrade_is_a_noop_when_the_legacy_constraint_is_already_there(monkeypatch):
    legacy = [("uq_x", ["user_id", "idempotency_key"])]
    assert _run_downgrade(monkeypatch, {"payments": legacy, "orders": legacy}) == []


def test_downgrade_never_touches_unrelated_unique_constraints(monkeypatch):
    other = ("uq_payments_provider_external_ref", ["provider", "external_ref"])
    calls = _run_downgrade(monkeypatch, {"payments": [other], "orders": [other]})
    assert all(c[0] == "create" for c in calls) and len(calls) == 2


@pytest.mark.integration
async def test_downgrade_roundtrip_on_real_postgres():
    url = os.environ.get("TEST_PG_URL", "").strip() or os.environ.get("MELORIN_DATABASE_URL", "").strip()
    if not url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL (TEST_PG_URL or MELORIN_DATABASE_URL)")
    m = _load()
    schema = f"t0003_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(url)

    def _unique_sets(conn):
        insp = sa.inspect(conn)
        return {t: sorted(sorted(u["column_names"]) for u in insp.get_unique_constraints(t)) for t in ("payments", "orders")}

    def _step(conn, fn):
        with Operations.context(MigrationContext.configure(conn)):
            fn()

    legacy, wanted = ["idempotency_key", "user_id"], ["idempotency_key", "store_id", "user_id"]
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await conn.execute(sa.text(f'SET search_path TO "{schema}"'))
            for t in ("payments", "orders"):  # fresh-install shape: generated three-column constraint name
                await conn.execute(
                    sa.text(
                        f"CREATE TABLE {t} (user_id int, store_id int, idempotency_key text, UNIQUE (user_id, store_id, idempotency_key))"
                    )
                )
            await conn.run_sync(_step, m.downgrade)
            assert await conn.run_sync(_unique_sets) == {"payments": [legacy], "orders": [legacy]}
            await conn.run_sync(_step, m.downgrade)  # idempotent
            assert await conn.run_sync(_unique_sets) == {"payments": [legacy], "orders": [legacy]}
            await conn.run_sync(_step, m.upgrade)  # and the way back up
            assert await conn.run_sync(_unique_sets) == {"payments": [wanted], "orders": [wanted]}
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
