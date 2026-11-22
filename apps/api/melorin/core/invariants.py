"""Runtime invariants that must survive ``python -O`` (unlike ``assert``, which is stripped)."""

from typing import TypeVar

from melorin.domain.invariants import InvariantViolation

__all__ = ["InvariantViolation", "require"]

T = TypeVar("T")


def require(value: T | None, what: str = "value") -> T:
    """Return ``value`` narrowed to non-None, or raise ``InvariantViolation``."""
    if value is None:
        raise InvariantViolation(f"invariant violated: {what} is None")
    return value
