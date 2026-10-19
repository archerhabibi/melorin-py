"""Migration 0026: legacy ``reseller_credit`` wallets are merged into the owner's ordinary Main Store wallet.

Runs the real ``upgrade()`` against an in-memory SQLite database built from the models.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import melorin.models  # noqa: F401  (registers every table)
from melorin.core.db import Base

MIGRATION = Path(__file__).resolve().parents[1] / "alembic/versions/0026_merge_reseller_credit_wallets.py"


def _load():
    spec = importlib.util.spec_from_file_location("migration_0026", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_upgrade(conn) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        _load().upgrade()


def _seed(conn):
    """Raw inserts (FK enforcement is off in SQLite) so the test only needs the tables the migration touches."""
    store = uuid.uuid4()
    ids = {}

    def wallet(name, user, kind, currency, balance):
        wid = uuid.uuid4()
        ids[name] = wid
        conn.execute(
            sa.text(
                "INSERT INTO wallets (id, user_id, store_id, kind, currency, balance) VALUES (:id, :u, :s, :k, :c, :b)"
            ),
            {"id": wid.hex, "u": user.hex, "s": store.hex, "k": kind, "c": currency, "b": balance},
        )

    users = [uuid.uuid4() for _ in range(5)]
    wallet("a_legacy", users[0], "reseller_credit", "IRT", 50_000)
    wallet("a_cust", users[0], "customer", "IRT", 10_000)
    wallet("b_legacy", users[1], "reseller_credit", "IRT", -30_000)  # debt, no customer wallet yet
    wallet("c_legacy", users[2], "reseller_credit", "IRT", 0)
    wallet("d_legacy_irt", users[3], "reseller_credit", "IRT", 5_000)
    wallet("d_legacy_usd", users[3], "reseller_credit", "USD", 7)
    wallet("d_cust_irt", users[3], "customer", "IRT", 1_000)
    wallet("e_legacy", users[4], "reseller_credit", "IRT", -20_000)
    wallet("e_cust", users[4], "customer", "IRT", 100_000)
    return store, users, ids


def _balance(conn, user, store, kind, currency="IRT"):
    row = conn.execute(
        sa.text("SELECT balance FROM wallets WHERE user_id=:u AND store_id=:s AND kind=:k AND currency=:c"),
        {"u": user.hex, "s": store.hex, "k": kind, "c": currency},
    ).first()
    return None if row is None else row[0]


def test_merge_moves_legacy_balances_into_the_customer_wallet_with_balanced_ledger():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        store, users, _ = _seed(conn)
        _run_upgrade(conn)

        assert _balance(conn, users[0], store, "customer") == 60_000  # existing wallet + legacy credit
        assert _balance(conn, users[1], store, "customer") == -30_000  # wallet created; legacy debt carried over
        assert _balance(conn, users[2], store, "customer") == 0  # wallet created, nothing to move
        assert _balance(conn, users[3], store, "customer") == 6_000
        assert _balance(conn, users[3], store, "customer", "USD") == 7  # other currency -> its own wallet
        assert _balance(conn, users[4], store, "customer") == 80_000  # debt reduces the existing balance
        for u, cur in [(users[0], "IRT"), (users[1], "IRT"), (users[2], "IRT"), (users[3], "IRT"), (users[3], "USD"), (users[4], "IRT")]:
            assert _balance(conn, u, store, "reseller_credit", cur) == 0

        # one balanced transaction per non-zero legacy wallet, none for the empty one
        txs = conn.execute(sa.text("SELECT id, kind FROM ledger_transactions")).all()
        assert len(txs) == 5 and {t[1] for t in txs} == {"wallet_merge"}
        assert conn.execute(sa.text("SELECT COALESCE(SUM(amount), 0) FROM ledger_entries")).scalar() == 0
        for (txid, _) in txs:
            assert conn.execute(sa.text("SELECT COALESCE(SUM(amount), 0) FROM ledger_entries WHERE transaction_id=:t"), {"t": txid}).scalar() == 0
        # balance_after of the credited side matches the resulting customer balance
        after = conn.execute(
            sa.text("SELECT e.balance_after FROM ledger_entries e JOIN wallets w ON w.id = e.wallet_id WHERE w.user_id=:u AND w.kind='customer' AND e.amount > 0"),
            {"u": users[0].hex},
        ).scalar()
        assert after == 60_000


def test_merge_is_idempotent_when_run_twice():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        store, users, _ = _seed(conn)
        _run_upgrade(conn)
        before = conn.execute(sa.text("SELECT COUNT(*) FROM ledger_transactions")).scalar()
        _run_upgrade(conn)  # legacy wallets are empty now -> nothing more to move
        assert conn.execute(sa.text("SELECT COUNT(*) FROM ledger_transactions")).scalar() == before
        assert _balance(conn, users[0], store, "customer") == 60_000
        assert _balance(conn, users[4], store, "customer") == 80_000


def test_revision_chain_has_a_single_head_after_0025():
    mod = _load()
    assert mod.down_revision == "0025_reseller_bot_runtime"
    assert len(mod.revision) <= 32  # alembic_version.version_num is VARCHAR(32)
