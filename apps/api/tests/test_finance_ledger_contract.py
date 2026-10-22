from pathlib import Path

from _source import read_source


def test_ledger_insert_handles_concurrent_idempotency_race():
    source = read_source(Path(__file__).parents[1].joinpath("melorin", "modules", "wallet", "service.py"))
    assert "begin_nested" in source
    assert "IntegrityError" in source
    assert "return existing, False" in source


def test_sales_summary_is_currency_grouped():
    source = read_source(Path(__file__).parents[1].joinpath("melorin", "modules", "admin", "router.py"))
    assert "Payment.currency" in source
    assert "group_by(Payment.currency)" in source
    assert "currency_safe" in source
