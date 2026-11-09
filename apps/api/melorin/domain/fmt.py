"""One place for money text (audit T12). Pure: ``domain`` imports nothing of ours."""


def money(amount: int | None, currency: str | None = None) -> str:
    """``1200000`` -> ``1,200,000``; with a currency -> ``1,200,000 IRT``. ``None`` counts as zero."""
    return f"{int(amount or 0):,}" + (f" {currency}" if currency else "")


def money_by_currency(rows: list[tuple[str, int]]) -> str:
    """``[(currency, total)]`` -> ``1,200,000 IRT + 30 USD`` (one part per currency, never mixed; empty -> ``۰``)."""
    parts = [money(total, cur) for cur, total in rows if total]
    return " + ".join(parts) if parts else "۰"
