"""Shared money formatting (audit T12: three private ``_money`` copies in orders/eventcenter)."""

from __future__ import annotations


def format_amount(amount: int | None, currency: str | None = None) -> str:
    """``1200000`` -> ``1,200,000``; with a currency -> ``1,200,000 IRT``. ``None`` counts as 0."""
    return f"{int(amount or 0):,}" + (f" {currency}" if currency else "")


def format_totals(rows: list[tuple[str, int]]) -> str:
    """``[(currency, total)]`` -> ``1,200,000 IRT + 5 USD`` (one part per currency, never mixed; empty -> ``۰``)."""
    parts = [format_amount(total, cur) for cur, total in rows if total]
    return " + ".join(parts) if parts else "۰"
