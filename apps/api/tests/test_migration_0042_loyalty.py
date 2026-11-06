"""Migration 0042 creates exactly the loyalty tables the models describe (no drift) and removes them again on downgrade."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations

import melorin.models  # noqa: F401  (registers every table)
from melorin.core.db import Base

LOYALTY = {
    "loyalty_programs",
    "loyalty_tiers",
    "loyalty_accounts",
    "loyalty_transactions",
    "loyalty_rewards",
    "loyalty_redemptions",
}
VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _migration():
    spec = importlib.util.spec_from_file_location("m0042", VERSIONS / "0042_customer_loyalty_club.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine_without_loyalty():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in LOYALTY])
    return engine


def test_revision_chain_is_linear():
    m = _migration()
    assert (m.revision, m.down_revision) == ("0042_customer_loyalty_club", "0041_panel_admin_guards")


def test_upgrade_matches_the_models_and_downgrade_removes_every_table():
    m = _migration()
    with _engine_without_loyalty().begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            m.upgrade()
        assert LOYALTY <= set(sa.inspect(conn).get_table_names())
        drift = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
        assert drift == []
        with Operations.context(MigrationContext.configure(conn)):
            m.downgrade()
        assert not LOYALTY & set(sa.inspect(conn).get_table_names())
