from dataclasses import dataclass


class LedgerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Line:
    """One leg of a double-entry transaction. Positive = credit to account, negative = debit."""

    account: str
    amount: int
    wallet_key: object | None = None  # wallet id when the account is a user wallet
    min_balance: int | None = 0  # lowest allowed resulting balance (None = unchecked, e.g. reversals)


def validate_balanced(lines: list[Line]) -> None:
    if not lines:
        raise LedgerError("LEDGER_EMPTY", "تراکنش بدون سطر است.")
    if any(not isinstance(l.amount, int) for l in lines):
        raise LedgerError("LEDGER_NOT_INTEGER", "مبالغ باید عدد صحیح باشند.")
    if any(l.amount == 0 for l in lines):
        raise LedgerError("LEDGER_ZERO_LINE", "سطر با مبلغ صفر مجاز نیست.")
    if sum(l.amount for l in lines) != 0:
        raise LedgerError("LEDGER_UNBALANCED", "تراکنش تراز نیست.")


def apply_to_balance(balance: int, line: Line) -> int:
    new = balance + line.amount
    if line.min_balance is not None and line.amount < 0 and new < line.min_balance:
        raise LedgerError("INSUFFICIENT_FUNDS", "موجودی کافی نیست.")
    return new


def reversal(lines: list[Line]) -> list[Line]:
    """Compensating lines (never mutate history). Reversal may push balances negative by policy."""
    return [Line(l.account, -l.amount, l.wallet_key, None) for l in lines]
