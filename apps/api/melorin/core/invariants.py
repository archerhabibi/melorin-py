"""Runtime invariants that must survive ``python -O`` (unlike ``assert``, which is stripped)."""

from typing import TypeVar

T = TypeVar("T")


class InvariantViolation(RuntimeError):
    """A condition the code guarantees was false: a bug, never a user error (maps to a 500 and is logged)."""


def require(value: T | None, what: str = "value") -> T:
    """Return ``value`` narrowed to non-None, or raise ``InvariantViolation``."""
    if value is None:
        raise InvariantViolation(f"invariant violated: {what} is None")
    return value
