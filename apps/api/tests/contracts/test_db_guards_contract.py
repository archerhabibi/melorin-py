"""DB-001: the foreign keys the code filters on keep a supporting index (a missing one only shows up as a slow query at scale)."""

from melorin import models  # noqa: F401  (registers every table)
from melorin.core.db import Base


def _indexed_prefixes(table: str) -> set[tuple[str, ...]]:
    t = Base.metadata.tables[table]
    prefixes = {tuple(c.name for c in ix.columns) for ix in t.indexes}
    for con in t.constraints:
        if con.__class__.__name__ == "UniqueConstraint":
            prefixes.add(tuple(c.name for c in con.columns))
    return prefixes


def test_queried_foreign_keys_have_a_leading_index():
    # per-panel account lists, an account's orders, receipt-file lookups
    for table, cols in [("vpn_accounts", ("panel_id", "status")), ("orders", ("vpn_account_id",)), ("payments", ("receipt_file_id",))]:
        assert cols in _indexed_prefixes(table), f"{table}{cols} lost its index (DB-001)"


def test_a_ledger_transaction_can_be_reversed_only_once_in_the_schema():
    t = Base.metadata.tables["ledger_transactions"]
    ix = next(i for i in t.indexes if i.name == "uq_ledger_transactions_reverses_id")
    assert ix.unique and [c.name for c in ix.columns] == ["reverses_id"]
