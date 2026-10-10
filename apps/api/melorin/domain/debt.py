"""Reseller debt limit rules.

Convention (doc 07 technical proposal): debt_limit is the positive maximum absolute debt.
Sales stop when balance <= -debt_limit. A sale is allowed only if balance - cost >= -debt_limit.
"""
from enum import StrEnum


class DebtState(StrEnum):
    OK = "ok"
    NEAR = "near"
    REACHED = "reached"


def can_afford(balance: int, cost: int, debt_limit: int) -> bool:
    if balance <= -debt_limit:
        return False
    return balance - cost >= -debt_limit


def min_balance(debt_limit: int) -> int:
    return -debt_limit


def state(balance: int, debt_limit: int, near_ratio: float = 0.8) -> DebtState:
    if balance <= -debt_limit:
        return DebtState.REACHED
    if debt_limit > 0 and balance < 0 and -balance >= debt_limit * near_ratio:
        return DebtState.NEAR
    return DebtState.OK
